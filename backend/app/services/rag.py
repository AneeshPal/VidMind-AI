
import re

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

from app.services.transcript import extract_transcript


# --------------------------------------------------
# GLOBAL STORAGE
# --------------------------------------------------

video_stores = {}
video_documents = {}
video_metadata = {}


# --------------------------------------------------
# MODELS
# --------------------------------------------------

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small"
)

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2
)


# --------------------------------------------------
# PASS 1: SPEAKER AND ROLE ANALYSIS
# --------------------------------------------------

identity_prompt = ChatPromptTemplate.from_template("""
You are an evidence analyst for VidMind, a YouTube video assistant.

Your task is to analyze the provided transcript excerpts and video metadata.

Identify the people involved in the video and their roles.

Possible roles:
- Host
- Interviewer
- Guest
- Main speaker
- Presenter
- Teacher
- Co-host
- Other participant

IMPORTANT RULES:

1. Distinguish the person speaking from the person being discussed.
2. Distinguish a host introducing a guest from the guest introducing themselves.
3. A sentence such as:
   "Sam Altman, welcome to the show"
   means someone is welcoming Sam Altman.
   It does NOT mean Sam Altman introduced himself.
4. A sentence such as:
   "Hi, I am Sam Altman"
   is a self-introduction.
5. Use conversational clues to identify who asks questions and who answers.
6. A video title or channel name can provide clues, but it is not
   transcript evidence.
7. Do not assume that the channel owner is always the interviewer.
8. Names may appear in Hindi, English, or Hinglish.
9. Transcripts may contain speech recognition errors.
10. Never invent names or roles.

For every identified person, provide:

- Name
- Possible role
- Evidence from transcript
- Timestamp
- Evidence source: Transcript or Metadata
- Confidence: High, Medium, or Low

Also answer these separately:

A. Who appears to be the host/interviewer?
B. Who appears to be the guest/main speaker?
C. Does the guest explicitly introduce themselves?
D. Does the host introduce the guest?
E. Which roles remain uncertain?

If the transcript does not establish a role, say so.

VIDEO METADATA:
{metadata}

TRANSCRIPT EXCERPTS:
{context}

Return a clear, structured analysis.
""")


# --------------------------------------------------
# PASS 2: FINAL ANSWER
# --------------------------------------------------

answer_prompt = ChatPromptTemplate.from_template("""
You are VidMind, an intelligent YouTube video assistant.

Answer the user's question using the transcript context and speaker analysis.

USER QUESTION:
{question}

VIDEO METADATA:
{metadata}

TRANSCRIPT EVIDENCE:
{context}

SPEAKER ANALYSIS:
{identity_analysis}

IMPORTANT RULES:

1. Understand English, Hindi, and Hinglish.
2. Never invent names, identities, or events.
3. Do not confuse the host with the guest.
4. Do not confuse a host's introduction with a guest's self-introduction.
5. If someone says "Welcome, Sam Altman", the person being welcomed
   is Sam Altman. This is not proof that Sam introduced himself.
6. Use transcript evidence to establish what was actually said.
7. Metadata may help identify people, but clearly distinguish it
   from transcript evidence.
8. If the interviewer is identified only through metadata,
   explicitly mention that.
9. If evidence is insufficient, say that the identity or role
   cannot be confirmed.
10. Include timestamps when transcript evidence supports the answer.
11. Answer the actual question directly.
12. Do not provide the entire speaker analysis unless requested.

FINAL ANSWER:
""")


# --------------------------------------------------
# NORMAL QUESTION PROMPT
# --------------------------------------------------

normal_prompt = ChatPromptTemplate.from_template("""
You are VidMind, an AI assistant that answers questions about YouTube videos.

Answer using only the transcript context provided.

Rules:
1. Understand English, Hindi, and Hinglish.
2. Account for possible speech-to-text errors.
3. Never invent facts.
4. If the answer is unavailable in the transcript, say so.
5. Include relevant timestamps when useful.
6. Keep the answer direct and conversational.

VIDEO:
{metadata}

TRANSCRIPT:
{context}

QUESTION:
{question}

ANSWER:
""")


# --------------------------------------------------
# TIMESTAMP FORMATTER
# --------------------------------------------------

def format_timestamp(seconds):
    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60

    if hours:
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{remaining_seconds:02d}"
        )

    return f"{minutes:02d}:{remaining_seconds:02d}"


# --------------------------------------------------
# DOCUMENT CREATION
# --------------------------------------------------

def create_timestamped_documents(segments):
    documents = []

    chunk_size = 1000
    overlap = 200

    current_text = ""
    chunk_start = None
    chunk_end = None

    for segment in segments:
        text = segment["text"].strip()

        if not text:
            continue

        start = float(segment["start"])
        end = start + float(segment["duration"])

        if chunk_start is None:
            chunk_start = start

        current_text += text + " "
        chunk_end = end

        if len(current_text) >= chunk_size:
            documents.append(
                Document(
                    page_content=current_text.strip(),
                    metadata={
                        "start": chunk_start,
                        "end": chunk_end
                    }
                )
            )

            current_text = current_text[-overlap:]
            chunk_start = max(0, chunk_end - 20)

    if current_text.strip():
        documents.append(
            Document(
                page_content=current_text.strip(),
                metadata={
                    "start": chunk_start or 0,
                    "end": chunk_end or 0
                }
            )
        )

    return documents


# --------------------------------------------------
# SPEAKER QUESTION DETECTION
# --------------------------------------------------

def is_speaker_question(question):

    patterns = [
        r"\bspeaker\b",
        r"\bwho is speaking\b",
        r"\bwho is talking\b",
        r"\bpresenter\b",
        r"\bhost\b",
        r"\bguest\b",
        r"\binterviewer\b",
        r"\bperson in the video\b",
        r"\bwho is this\b",
        r"\bwho is teaching\b",
        r"\bteacher\b",
        r"\bparticipants\b",
        r"\bname of the person\b",
        r"\bwho are they\b",
        r"\bintroduce(?:d|s)? themselves\b",
        r"\bself introduction\b",
        r"\bintroduces himself\b",
        r"\bintroduces herself\b",
        r"\bwho interviewed\b",
        r"\bwho interviews\b",
        r"कौन बोल",
        r"कौन बात",
        r"कौन पढ़ा",
        r"किसका नाम",
        r"कौन है",
        r"इंटरव्यू किसने"
    ]

    question = question.lower()

    return any(
        re.search(pattern, question)
        for pattern in patterns
    )


# --------------------------------------------------
# IDENTITY CHUNK SEARCH
# --------------------------------------------------

def find_identity_chunks(documents):

    patterns = [
        r"\bmy name is\b",
        r"\bi am\b",
        r"\bi'm\b",
        r"\bthis is\b",
        r"\bwelcome back\b",
        r"\bwelcome to\b",
        r"\bmyself\b",
        r"\bmy channel\b",
        r"\bhosted by\b",
        r"\bjoining me\b",
        r"\bwith me\b",
        r"\bmeet\b",
        r"\bintroducing\b",
        r"\bmera naam\b",
        r"\bmain hoon\b",
        r"\bmai hoon\b",
        r"\bhamara channel\b",
        r"\bमेरा नाम\b",
        r"\bमैं हूं\b",
        r"\bमैं हूँ\b",
        r"\bहमारा चैनल\b",
        r"\bस्वागत है\b",
        r"\bनमस्कार\b"
    ]

    matches = []

    for document in documents:
        content = document.page_content.lower()

        if any(
            re.search(pattern, content)
            for pattern in patterns
        ):
            matches.append(document)

    return matches


# --------------------------------------------------
# REMOVE DUPLICATE DOCUMENTS
# --------------------------------------------------

def deduplicate_documents(documents):

    unique_documents = []
    seen = set()

    for document in documents:

        key = (
            document.metadata.get("start"),
            document.metadata.get("end"),
            document.page_content
        )

        if key not in seen:
            seen.add(key)
            unique_documents.append(document)

    return unique_documents


# --------------------------------------------------
# IDENTITY CONTEXT RETRIEVAL
# --------------------------------------------------

def retrieve_identity_context(
    vector_store,
    all_documents,
    question
):

    candidates = []

    # Search the full transcript for possible introductions
    candidates.extend(
        find_identity_chunks(all_documents)
    )

    # Semantic identity searches
    identity_queries = [
        "The speaker introduces themselves and says their name.",
        "The presenter tells the audience who they are.",
        "The host introduces the guest and interviewer.",
        "A person says their name and role in the video.",
        "The interviewer asks questions to the guest.",
        "The guest responds to the interviewer's questions.",
        "The speaker introduces themselves in Hindi or Hinglish."
    ]

    for query in identity_queries:

        results = vector_store.similarity_search(
            query,
            k=3
        )

        candidates.extend(results)

    # Actual user question
    candidates.extend(
        vector_store.similarity_search(
            question,
            k=5
        )
    )

    candidates = deduplicate_documents(candidates)

    return candidates[:15]


# --------------------------------------------------
# FORMAT TRANSCRIPT CONTEXT
# --------------------------------------------------

def format_docs(documents):

    formatted = []

    for document in documents:

        start = format_timestamp(
            document.metadata.get("start", 0)
        )

        end = format_timestamp(
            document.metadata.get("end", 0)
        )

        formatted.append(
            f"[Timestamp: {start} - {end}]\n"
            f"{document.page_content}"
        )

    return "\n\n".join(formatted)


# --------------------------------------------------
# FORMAT VIDEO METADATA
# --------------------------------------------------

def format_metadata(video_id):

    metadata = video_metadata.get(video_id, {})

    title = metadata.get("title") or "Not provided"
    channel = metadata.get("channel_name") or "Not provided"

    return (
        f"Video ID: {video_id}\n"
        f"Video title: {title}\n"
        f"Channel name: {channel}"
    )


# --------------------------------------------------
# PROCESS VIDEO
# --------------------------------------------------

def process_video(
    video_id,
    title=None,
    channel_name=None
):

    print(f"\nProcessing video: {video_id}")

    segments = extract_transcript(video_id)

    documents = create_timestamped_documents(segments)

    if not documents:
        raise ValueError("No transcript chunks were created.")

    vector_store = FAISS.from_documents(
        documents,
        embeddings
    )

    video_stores[video_id] = vector_store
    video_documents[video_id] = documents

    video_metadata[video_id] = {
        "title": title,
        "channel_name": channel_name
    }

    print("\n========== VIDEO PROCESSING ==========")
    print("Video ID:", video_id)
    print("Title:", title)
    print("Channel:", channel_name)
    print("Transcript segments:", len(segments))
    print("Total chunks:", len(documents))
    print("======================================\n")

    return {
        "video_id": video_id,
        "chunks": len(documents),
        "message": "Video processed successfully."
    }


# --------------------------------------------------
# ASK QUESTION
# --------------------------------------------------

def ask_question(video_id, question):

    if video_id not in video_stores:
        raise ValueError(
            "Video has not been processed yet."
        )

    vector_store = video_stores[video_id]

    metadata = format_metadata(video_id)

    # ----------------------------------------------
    # TWO-PASS RAG FOR SPEAKER QUESTIONS
    # ----------------------------------------------

    if is_speaker_question(question):

        print("\n========== TWO-PASS RAG ==========")

        identity_documents = retrieve_identity_context(
            vector_store,
            video_documents[video_id],
            question
        )

        identity_context = format_docs(
            identity_documents
        )

        print(
            "Identity evidence chunks:",
            len(identity_documents)
        )

        # PASS 1: Analyze identities and roles
        identity_chain = (
            identity_prompt
            | llm
            | StrOutputParser()
        )

        identity_analysis = identity_chain.invoke({
            "context": identity_context,
            "metadata": metadata
        })

        print("\nPASS 1 - IDENTITY ANALYSIS:")
        print(identity_analysis)

        # PASS 2: Generate final answer
        answer_chain = (
            answer_prompt
            | llm
            | StrOutputParser()
        )

        answer = answer_chain.invoke({
            "question": question,
            "context": identity_context,
            "metadata": metadata,
            "identity_analysis": identity_analysis
        })

        print("\nPASS 2 - FINAL ANSWER:")
        print(answer)

        print("=================================\n")

        return answer

    # ----------------------------------------------
    # NORMAL ONE-PASS RAG
    # ----------------------------------------------

    retrieved_documents = vector_store.similarity_search(
        question,
        k=8
    )

    context = format_docs(retrieved_documents)

    chain = normal_prompt | llm | StrOutputParser()

    answer = chain.invoke({
        "context": context,
        "question": question,
        "metadata": metadata
    })

    return answer
