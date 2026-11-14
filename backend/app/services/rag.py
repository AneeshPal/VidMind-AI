
import math
import re
from collections import Counter

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

from app.services.transcript import extract_transcript

from app.services.storage import (
    get_video_cache_path,
    save_video_metadata,
    load_video_metadata,
    cache_exists
)


# ==================================================
# GLOBAL STORAGE
# ==================================================

video_stores = {}
video_documents = {}
video_metadata = {}
video_segments = {}


# ==================================================
# MODELS
# ==================================================

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small"
)

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2
)


# ==================================================
# CONFIGURATION
# ==================================================

CHUNK_SIZE = 1500
RETRIEVAL_LIMIT = 8
ANALYSIS_BATCH_SIZE = 10
NEIGHBOR_WINDOW = 1


# ==================================================
# PROMPTS
# ==================================================

rewrite_prompt = ChatPromptTemplate.from_template("""
You are a question understanding assistant.

Convert the latest user question into a standalone question.

Use conversation history to understand references and follow-ups.

Rules:
- Preserve the user's original intent.
- Resolve references such as he, she, they, it, that and those.
- Do not answer the question.
- Do not add assumptions.
- Return only the standalone question.

Conversation history:
{chat_history}

Latest question:
{question}

Standalone question:
""")

query_expansion_prompt = ChatPromptTemplate.from_template("""
You generate search queries for a YouTube transcript.

Generate exactly two alternative queries useful for retrieving
evidence for the user's question.

Rules:
- Preserve the original intent.
- Include relevant synonyms and related expressions.
- Do not answer the question.
- Do not introduce unrelated topics.
- Return one query per line without numbering.

Question:
{question}

Alternative queries:
""")

answer_prompt = ChatPromptTemplate.from_template("""
You are VidMind, an AI assistant that answers questions about
the currently watched YouTube video.

VIDEO INFORMATION:
{metadata}

CONVERSATION HISTORY:
{chat_history}

USER QUESTION:
{question}

RETRIEVED TRANSCRIPT EVIDENCE:
{context}

RULES:
1. Answer the actual question using the transcript evidence.
2. Do not invent names, facts, statistics or events.
3. Use conversation history to understand follow-up questions.
4. If evidence is incomplete, explain what is known and missing.
5. Do not claim something was never mentioned merely because
   it is absent from the retrieved passages.
6. Include timestamps when useful.
7. Distinguish the host, interviewer, guest and other people.
8. Keep the response clear and conversational.

Answer:
""")

summary_prompt = ChatPromptTemplate.from_template("""
Analyze this section of a YouTube transcript.

Create a factual summary covering:
- Main topics
- Important explanations and arguments
- Examples and stories
- Names, events and ideas
- Relevant timestamps

Do not invent information.

Transcript section:
{context}

Section summary:
""")

final_summary_prompt = ChatPromptTemplate.from_template("""
Combine these section summaries into one coherent summary
of the complete YouTube video.

Video information:
{metadata}

Section summaries:
{summaries}

Instructions:
- Cover the major topics throughout the video.
- Preserve important arguments and explanations.
- Avoid repetition.
- Use clear headings.
- Include timestamps where available.
- Do not invent details.

Complete video summary:
""")

takeaways_prompt = ChatPromptTemplate.from_template("""
Extract important key takeaways from this transcript section.

Focus on:
- Important insights
- Advice and recommendations
- Main arguments
- Lessons and conclusions
- Important facts and examples

Only include points supported by the transcript.
Include timestamps where possible.

Transcript:
{context}

Key takeaways:
""")

combine_takeaways_prompt = ChatPromptTemplate.from_template("""
Combine the following key takeaways from different sections
of the same YouTube video.

Instructions:
- Remove duplicates.
- Organize the most important insights.
- Preserve useful details.
- Include timestamps where available.
- Do not invent information.

Section takeaways:
{analyses}

Final key takeaways:
""")

people_prompt = ChatPromptTemplate.from_template("""
Analyze this section of a YouTube transcript to identify people.

Identify people only when the transcript provides evidence.

For each person, report:
- Name, if available
- Role or relationship to the discussion
- What they said or did
- Timestamp, if available

Rules:
- Do not assume the host and guest are the same person.
- Do not infer someone's identity from the video title alone.
- If a name is uncertain, explicitly state that.
- Distinguish people participating from people merely mentioned.

Transcript:
{context}

People identified:
""")

combine_people_prompt = ChatPromptTemplate.from_template("""
Combine the following analyses of different sections of a video.

Create a deduplicated list of people mentioned or participating.

For each person, include:
- Name
- Role in the video, if established
- Supporting evidence
- Timestamp, if available

Do not merge two people just because their roles are similar.
Do not invent identities.

Video metadata:
{metadata}

Section analyses:
{analyses}

Final people analysis:
""")


# ==================================================
# GENERAL HELPERS
# ==================================================

def format_metadata(video_id):
    metadata = video_metadata.get(video_id, {})

    return (
        f"Video title: {metadata.get('title') or 'Not available'}\n"
        f"Channel name: {metadata.get('channel_name') or 'Not available'}"
    )


def format_chat_history(chat_history):
    if not chat_history:
        return "No previous conversation."

    messages = []

    for message in chat_history[-10:]:
        role = message.get("role", "user").capitalize()
        content = message.get("content", "")

        if content.strip():
            messages.append(f"{role}: {content.strip()}")

    return "\n".join(messages) or "No previous conversation."


def timestamp_string(seconds):
    seconds = max(0, int(seconds or 0))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60

    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"

    return f"{minutes:02d}:{remaining_seconds:02d}"


def format_docs(docs):
    formatted = []

    for doc in docs:
        start = doc.metadata.get("start", 0)
        timestamp = timestamp_string(start)

        formatted.append(
            f"[Timestamp: {timestamp}]\n{doc.page_content}"
        )

    return "\n\n".join(formatted)


def unique_documents(docs):
    unique = []
    seen = set()

    for doc in docs:
        key = (
            doc.page_content,
            doc.metadata.get("start")
        )

        if key not in seen:
            seen.add(key)
            unique.append(doc)

    return unique


def split_into_batches(items, batch_size):
    for index in range(0, len(items), batch_size):
        yield items[index:index + batch_size]


# ==================================================
# OPTIMIZED TRANSCRIPT CHUNKING
# ==================================================

def create_transcript_documents(transcript_segments):
    """
    Combine individual transcript segments into larger
    chronological documents while preserving timestamps.
    """

    documents = []

    current_lines = []
    current_length = 0

    chunk_start = None
    chunk_end = None

    for segment in transcript_segments:

        text = segment["text"].strip()

        if not text:
            continue

        start = float(segment["start"])
        duration = float(segment["duration"])
        end = start + duration

        timestamp = timestamp_string(start)
        line = f"[{timestamp}] {text}"

        if current_lines and current_length + len(line) > CHUNK_SIZE:

            documents.append(
                Document(
                    page_content="\n".join(current_lines),
                    metadata={
                        "start": chunk_start,
                        "end": chunk_end,
                        "duration": chunk_end - chunk_start
                    }
                )
            )

            current_lines = []
            current_length = 0
            chunk_start = None
            chunk_end = None

        if chunk_start is None:
            chunk_start = start

        current_lines.append(line)
        current_length += len(line) + 1
        chunk_end = end

    if current_lines:
        documents.append(
            Document(
                page_content="\n".join(current_lines),
                metadata={
                    "start": chunk_start,
                    "end": chunk_end,
                    "duration": chunk_end - chunk_start
                }
            )
        )

    for index, document in enumerate(documents):
        document.metadata["chunk_index"] = index

    return documents


# ==================================================
# QUESTION UNDERSTANDING
# ==================================================

def rewrite_follow_up_question(question, chat_history):

    if not chat_history:
        return question

    try:
        chain = rewrite_prompt | llm | StrOutputParser()

        result = chain.invoke({
            "question": question,
            "chat_history": format_chat_history(chat_history)
        })

        result = result.strip().strip('"').strip("'")

        return result or question

    except Exception as error:
        print("Question rewriting error:", error)
        return question


def expand_search_queries(question):

    queries = [question]

    try:
        chain = query_expansion_prompt | llm | StrOutputParser()

        result = chain.invoke({
            "question": question
        })

        for line in result.splitlines():

            cleaned = re.sub(
                r"^\s*[-*\d.)]+\s*",
                "",
                line
            ).strip()

            if cleaned and cleaned.lower() != question.lower():
                queries.append(cleaned)

    except Exception as error:
        print("Query expansion error:", error)

    return list(dict.fromkeys(queries))[:3]


# ==================================================
# KEYWORD RETRIEVAL
# ==================================================

def tokenize(text):
    return re.findall(r"\b[a-zA-Z0-9']+\b", text.lower())


def keyword_search(documents, query, limit=8):

    query_terms = tokenize(query)

    if not query_terms or not documents:
        return []

    document_tokens = [
        tokenize(doc.page_content)
        for doc in documents
    ]

    document_count = len(documents)

    average_length = (
        sum(len(tokens) for tokens in document_tokens)
        / max(document_count, 1)
    )

    document_frequency = Counter()

    for tokens in document_tokens:
        document_frequency.update(set(tokens))

    scores = []

    k1 = 1.5
    b = 0.75

    for index, tokens in enumerate(document_tokens):

        frequencies = Counter(tokens)
        document_length = len(tokens)
        score = 0.0

        for term in query_terms:

            frequency = frequencies.get(term, 0)

            if frequency == 0:
                continue

            df = document_frequency.get(term, 0)

            inverse_frequency = math.log(
                1 + (
                    document_count - df + 0.5
                ) / (df + 0.5)
            )

            denominator = frequency + k1 * (
                1 - b + b * (
                    document_length / max(average_length, 1)
                )
            )

            score += (
                inverse_frequency
                * frequency
                * (k1 + 1)
                / denominator
            )

        if score > 0:
            scores.append((score, index))

    scores.sort(reverse=True)

    return [
        documents[index]
        for _, index in scores[:limit]
    ]


# ==================================================
# HYBRID RETRIEVAL
# ==================================================

def hybrid_retrieval(video_id, question, limit=RETRIEVAL_LIMIT):

    vector_store = video_stores[video_id]
    documents = video_documents[video_id]

    queries = expand_search_queries(question)

    ranked_lists = []

    for query in queries:

        try:
            semantic_results = vector_store.similarity_search(
                query,
                k=limit
            )

            ranked_lists.append(semantic_results)

        except Exception as error:
            print("Semantic search error:", error)

        try:
            keyword_results = keyword_search(
                documents,
                query,
                limit=limit
            )

            ranked_lists.append(keyword_results)

        except Exception as error:
            print("Keyword search error:", error)

    # Reciprocal Rank Fusion.
    fused_scores = {}
    document_lookup = {}

    for ranked_list in ranked_lists:

        for rank, doc in enumerate(ranked_list):

            key = (
                doc.page_content,
                doc.metadata.get("start")
            )

            document_lookup[key] = doc

            fused_scores[key] = (
                fused_scores.get(key, 0)
                + 1 / (60 + rank + 1)
            )

    ranked_keys = sorted(
        fused_scores,
        key=lambda key: fused_scores[key],
        reverse=True
    )

    return [
        document_lookup[key]
        for key in ranked_keys[:limit]
    ]


# ==================================================
# CONTEXT EXPANSION
# ==================================================

def expand_with_neighbors(
    video_id,
    retrieved_docs,
    window=NEIGHBOR_WINDOW
):

    documents = video_documents[video_id]

    selected_indices = set()

    for doc in retrieved_docs:

        index = doc.metadata.get("chunk_index")

        if index is None:
            continue

        for neighbor_index in range(
            max(0, index - window),
            min(len(documents), index + window + 1)
        ):
            selected_indices.add(neighbor_index)

    expanded = [
        documents[index]
        for index in sorted(selected_indices)
    ]

    return unique_documents(expanded)


# ==================================================
# PERSISTENT FAISS CACHE
# ==================================================

def load_cached_video(video_id):
    """
    Load a previously saved FAISS index and documents.
    """

    if not cache_exists(video_id):
        return False

    try:
        cache_path = get_video_cache_path(video_id)

        vector_store = FAISS.load_local(
            str(cache_path),
            embeddings,
            allow_dangerous_deserialization=True
        )

        documents = []

        for doc_id in vector_store.index_to_docstore_id.values():

            document = vector_store.docstore.search(doc_id)

            if isinstance(document, Document):
                documents.append(document)

        documents.sort(
            key=lambda doc: doc.metadata.get("chunk_index", 0)
        )

        if not documents:
            print("Cache contains no documents.")
            return False

        metadata = load_video_metadata(video_id)

        video_stores[video_id] = vector_store
        video_documents[video_id] = documents
        video_metadata[video_id] = metadata

        print("\n========== CACHE LOADED ==========")
        print("Video ID:", video_id)
        print("Cached chunks:", len(documents))
        print("==================================\n")

        return True

    except Exception as error:
        print("Cache loading failed:", repr(error))

        # Do not leave partially loaded data in memory.
        video_stores.pop(video_id, None)
        video_documents.pop(video_id, None)
        video_metadata.pop(video_id, None)

        return False


# ==================================================
# TRANSCRIPT PROCESSING
# ==================================================

def process_video(video_id, title=None, channel_name=None):

    print("\n========== VIDEO PROCESSING ==========")
    print("Video ID:", video_id)
    print("Title:", title)
    print("Channel:", channel_name)

    # 1. Check in-memory cache.
    if video_id in video_stores:

        print("Video already loaded in memory.")

        metadata = video_metadata.get(video_id, {})

        if title:
            metadata["title"] = title

        if channel_name:
            metadata["channel_name"] = channel_name

        video_metadata[video_id] = metadata

        save_video_metadata(video_id, metadata)

        return {
            "video_id": video_id,
            "chunks": len(video_documents[video_id]),
            "title": metadata.get("title"),
            "channel_name": metadata.get("channel_name"),
            "cached": True
        }

    # 2. Try persistent cache.
    if load_cached_video(video_id):

        metadata = video_metadata[video_id]

        if title:
            metadata["title"] = title

        if channel_name:
            metadata["channel_name"] = channel_name

        save_video_metadata(video_id, metadata)

        print("Using persistent FAISS cache.")

        return {
            "video_id": video_id,
            "chunks": len(video_documents[video_id]),
            "title": metadata.get("title"),
            "channel_name": metadata.get("channel_name"),
            "cached": True
        }

    # 3. Extract transcript if no cache exists.
    print("No cache found. Extracting transcript...")

    transcript_segments = extract_transcript(video_id)

    if not transcript_segments:
        raise ValueError("No transcript available for this video.")

    video_metadata[video_id] = {
        "title": title,
        "channel_name": channel_name
    }

    video_segments[video_id] = transcript_segments

    print("Transcript segments:", len(transcript_segments))

    # 4. Create optimized documents.
    documents = create_transcript_documents(transcript_segments)

    if not documents:
        raise ValueError("Transcript processing produced no chunks.")

    print("Optimized chunks:", len(documents))

    # 5. Generate embeddings and build FAISS.
    vector_store = FAISS.from_documents(
        documents,
        embeddings
    )

    video_documents[video_id] = documents
    video_stores[video_id] = vector_store

    # 6. Save FAISS index.
    cache_path = get_video_cache_path(video_id)
    cache_path.mkdir(parents=True, exist_ok=True)

    vector_store.save_local(str(cache_path))

    # 7. Save metadata.
    save_video_metadata(
        video_id,
        video_metadata[video_id]
    )

    print("FAISS index saved successfully.")
    print("======================================\n")

    return {
        "video_id": video_id,
        "chunks": len(documents),
        "transcript_segments": len(transcript_segments),
        "title": title,
        "channel_name": channel_name,
        "cached": False
    }


# ==================================================
# FULL VIDEO ANALYSIS
# ==================================================

def analyze_full_transcript(video_id, prompt):

    documents = video_documents[video_id]

    section_analyses = []

    chain = prompt | llm | StrOutputParser()

    total_batches = math.ceil(
        len(documents) / ANALYSIS_BATCH_SIZE
    )

    print("Total analysis batches:", total_batches)

    for batch_number, batch in enumerate(
        split_into_batches(documents, ANALYSIS_BATCH_SIZE),
        start=1
    ):

        context = format_docs(batch)

        print(
            f"Analyzing batch {batch_number}/{total_batches}..."
        )

        try:
            result = chain.invoke({
                "context": context
            })

            if result.strip():
                section_analyses.append(
                    f"Section {batch_number}:\n{result.strip()}"
                )

        except Exception as error:
            print(
                f"Analysis error in batch {batch_number}:",
                error
            )

    return section_analyses


def summarize_video(video_id):

    print("Starting full-video summary...")

    section_summaries = analyze_full_transcript(
        video_id,
        summary_prompt
    )

    if not section_summaries:
        return "I couldn't generate a summary from the available transcript."

    combine_chain = final_summary_prompt | llm | StrOutputParser()

    answer = combine_chain.invoke({
        "metadata": format_metadata(video_id),
        "summaries": "\n\n".join(section_summaries)
    })

    return answer.strip()


def get_video_takeaways(video_id):

    print("Starting full-video takeaway extraction...")

    section_analyses = analyze_full_transcript(
        video_id,
        takeaways_prompt
    )

    if not section_analyses:
        return "I couldn't identify reliable takeaways from the transcript."

    chain = combine_takeaways_prompt | llm | StrOutputParser()

    return chain.invoke({
        "analyses": "\n\n".join(section_analyses)
    }).strip()


def identify_people(video_id):

    print("Starting full-video people identification...")

    section_analyses = analyze_full_transcript(
        video_id,
        people_prompt
    )

    if not section_analyses:
        return "I couldn't identify people reliably from the transcript."

    chain = combine_people_prompt | llm | StrOutputParser()

    return chain.invoke({
        "metadata": format_metadata(video_id),
        "analyses": "\n\n".join(section_analyses)
    }).strip()


# ==================================================
# QUESTION INTENT DETECTION
# ==================================================

def detect_global_question(question):

    normalized = question.lower().strip()

    summary_patterns = [
        r"\bsummarize\b",
        r"\bsummary of\b",
        r"\bvideo summary\b",
        r"\bgive me a summary\b",
        r"\bwhat is this video about\b"
    ]

    takeaway_patterns = [
        r"\bkey takeaways\b",
        r"\bmain takeaways\b",
        r"\bimportant lessons\b",
        r"\bmain lessons\b",
        r"\bmajor insights\b"
    ]

    people_patterns = [
        r"\bwho are the people\b",
        r"\bpeople in this video\b",
        r"\bwho is in this video\b",
        r"\bwho are featured\b",
        r"\bidentify the people\b",
        r"\blist the people\b"
    ]

    if any(re.search(p, normalized) for p in summary_patterns):
        return "summary"

    if any(re.search(p, normalized) for p in takeaway_patterns):
        return "takeaways"

    if any(re.search(p, normalized) for p in people_patterns):
        return "people"

    return None


def is_speaker_question(question):

    patterns = [
        r"\bwho is (the )?(speaker|host|interviewer|guest)\b",
        r"\bwho (is|are) (speaking|talking)\b",
        r"\bwhat is (the )?(speaker|host|guest)'?s name\b",
        r"\bwho introduced\b",
        r"\bintroduce themselves\b",
        r"\binterviewer\b",
        r"\bmain speaker\b",
        r"\bguest name\b",
        r"\bspeaker name\b",
        r"\bmera naam\b",
        r"\bkaun bol raha\b",
        r"\bkaun hai\b"
    ]

    return any(
        re.search(pattern, question, re.IGNORECASE)
        for pattern in patterns
    )


# ==================================================
# ANSWER GENERATION
# ==================================================

def answer_with_retrieved_context(
    video_id,
    question,
    chat_history,
    retrieved_docs
):

    context = format_docs(retrieved_docs)

    chain = answer_prompt | llm | StrOutputParser()

    answer = chain.invoke({
        "metadata": format_metadata(video_id),
        "chat_history": format_chat_history(chat_history),
        "question": question,
        "context": context
    })

    return answer.strip()


# ==================================================
# ASK QUESTION
# ==================================================

def ask_question(video_id, question, chat_history=None):

    # Restore video index if it is not in memory.
    if video_id not in video_stores:

        if not load_cached_video(video_id):
            raise ValueError(
                "Video has not been processed. Please process it first."
            )

    if not question.strip():
        raise ValueError("Question cannot be empty.")

    chat_history = chat_history or []

    print("\n========== QUESTION ANSWERING ==========")
    print("Original question:", question)

    # 1. Understand follow-up questions.
    standalone_question = rewrite_follow_up_question(
        question,
        chat_history
    )

    print("Standalone question:", standalone_question)

    # 2. Full-video analysis when required.
    global_intent = detect_global_question(standalone_question)

    if global_intent == "summary":
        print("Using full-transcript summary.")
        return summarize_video(video_id)

    if global_intent == "takeaways":
        print("Using full-transcript takeaway extraction.")
        return get_video_takeaways(video_id)

    if global_intent == "people":
        print("Using full-transcript people identification.")
        return identify_people(video_id)

    # 3. Hybrid retrieval for dynamic questions.
    print("Using hybrid retrieval.")

    retrieved_docs = hybrid_retrieval(
        video_id,
        standalone_question
    )

    if not retrieved_docs:
        return (
            "I couldn't find relevant transcript evidence "
            "to answer that question reliably."
        )

    # 4. Add neighboring context.
    expanded_docs = expand_with_neighbors(
        video_id,
        retrieved_docs
    )

    print("Retrieved chunks:", len(retrieved_docs))
    print("Chunks after context expansion:", len(expanded_docs))

    # 5. Generate grounded answer.
    answer = answer_with_retrieved_context(
        video_id=video_id,
        question=question,
        chat_history=chat_history,
        retrieved_docs=expanded_docs
    )

    print("========================================\n")

    return answer
