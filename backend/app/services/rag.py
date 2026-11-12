
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import (
    RunnableParallel,
    RunnablePassthrough,
    RunnableLambda
)
from langchain_core.output_parsers import StrOutputParser

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.transcript import extract_transcript


# Store FAISS indexes for processed videos.
video_stores = {}


# OpenAI models.
embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small"
)

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2
)


# Prompt with timestamp instructions.
prompt = PromptTemplate(
    template="""
You are VidMind, an AI assistant that answers questions about YouTube videos.

Answer the user's question using ONLY the provided transcript context.

Important rules:

1. Give accurate and useful answers.
2. Do not invent information that is not present in the transcript.
3. When referring to a specific discussion, include its timestamp.
4. Use the exact timestamp provided in the context.
5. Write timestamps in MM:SS format, for example [05:42].
6. If multiple relevant moments exist, include multiple timestamps.
7. If the information is unavailable, say:
   "I couldn't find this information in the video."
8. For summary questions, summarize the main topics and include timestamps for important sections.
9. For questions about people, identify them using the transcript.

Transcript context:

{context}

User question:

{question}

Answer:
""",
    input_variables=["context", "question"]
)


def format_timestamp(seconds: float) -> str:
    """Convert seconds to MM:SS or HH:MM:SS."""

    total_seconds = max(0, int(seconds))

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60

    if hours > 0:
        return (
            f"{hours}:"
            f"{minutes:02d}:"
            f"{remaining_seconds:02d}"
        )

    return f"{minutes:02d}:{remaining_seconds:02d}"


def create_timestamped_documents(segments):
    """
    Group transcript segments into chunks while preserving
    each chunk's starting and ending timestamps.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    documents = []

    current_segments = []
    current_length = 0

    for segment in segments:
        text = segment["text"]

        if current_segments and current_length + len(text) > 1000:
            first = current_segments[0]
            last = current_segments[-1]

            chunk_text = " ".join(
                item["text"] for item in current_segments
            )

            documents.append(
                Document(
                    page_content=chunk_text,
                    metadata={
                        "start": first["start"],
                        "end": last["start"] + last["duration"]
                    }
                )
            )

            # Keep approximately 200 characters of overlap.
            overlap_segments = []
            overlap_length = 0

            for item in reversed(current_segments):
                overlap_segments.insert(0, item)
                overlap_length += len(item["text"]) + 1

                if overlap_length >= 200:
                    break

            current_segments = overlap_segments
            current_length = overlap_length

        current_segments.append(segment)
        current_length += len(text) + 1

    # Add the final chunk.
    if current_segments:
        first = current_segments[0]
        last = current_segments[-1]

        chunk_text = " ".join(
            item["text"] for item in current_segments
        )

        documents.append(
            Document(
                page_content=chunk_text,
                metadata={
                    "start": first["start"],
                    "end": last["start"] + last["duration"]
                }
            )
        )

    return documents


def process_video(video_id: str):
    """
    Extract transcript, create timestamped chunks,
    generate embeddings and store them in FAISS.
    """

    if video_id in video_stores:
        return {
            "message": "Video already processed",
            "video_id": video_id,
            "status": "already_processed",
            "chunks": len(video_stores[video_id].index_to_docstore_id)
        }

    segments = extract_transcript(video_id)

    documents = create_timestamped_documents(segments)

    if not documents:
        raise ValueError("No transcript chunks were generated.")

    vector_store = FAISS.from_documents(
        documents,
        embeddings
    )

    video_stores[video_id] = vector_store

    print("Video processed successfully!")
    print("Video ID:", video_id)
    print("Total chunks:", len(documents))

    return {
        "message": "Video processing completed",
        "video_id": video_id,
        "status": "processed",
        "chunks": len(documents)
    }


def format_docs(docs):
    """
    Include timestamps with each retrieved transcript chunk.
    """

    formatted_documents = []

    for doc in docs:
        start = doc.metadata.get("start", 0)
        end = doc.metadata.get("end", start)

        start_time = format_timestamp(start)
        end_time = format_timestamp(end)

        formatted_documents.append(
            f"[Timestamp: {start_time} - {end_time}]\n"
            f"{doc.page_content}"
        )

    return "\n\n".join(formatted_documents)


def ask_question(video_id: str, question: str):
    """
    Retrieve relevant timestamped chunks and generate an answer.
    """

    if video_id not in video_stores:
        raise ValueError(
            "Video has not been processed. Please process it first."
        )

    vector_store = video_stores[video_id]

    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 6}
    )

    parallel_chain = RunnableParallel({
        "context": retriever | RunnableLambda(format_docs),
        "question": RunnablePassthrough()
    })

    main_chain = (
        parallel_chain
        | prompt
        | llm
        | StrOutputParser()
    )

    answer = main_chain.invoke(question)

    return answer
