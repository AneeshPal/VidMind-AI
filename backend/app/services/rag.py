
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate

from langchain_core.runnables import (
    RunnableParallel,
    RunnablePassthrough,
    RunnableLambda
)

from langchain_core.output_parsers import StrOutputParser

from app.services.transcript import extract_transcript


# Store vector databases for different videos
video_stores = {}


# Initialize embeddings
embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small"
)


# Initialize LLM
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2
)


# Prompt template
prompt = PromptTemplate(
    template="""
    You are VidMind, an AI assistant that answers
    questions about YouTube videos.

    Answer ONLY using the provided transcript context.

    If the context is insufficient, say:
    "I couldn't find this information in the video."

    Context:
    {context}

    Question:
    {question}

    Answer:
    """,
    input_variables=["context", "question"]
)


def process_video(video_id: str):
    """
    Extract transcript, split text, generate embeddings
    and store vectors in FAISS.
    """

    # Avoid processing the same video repeatedly
    if video_id in video_stores:
        return {
            "status": "already_processed",
            "chunks": None
        }

    # 1. Extract transcript
    transcript_text = extract_transcript(video_id)

    # 2. Split transcript
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )

    chunks = splitter.create_documents(
        [transcript_text]
    )

    if not chunks:
        raise ValueError("No transcript chunks were created.")

    # 3. Generate embeddings and create FAISS store
    vector_store = FAISS.from_documents(
        documents=chunks,
        embedding=embeddings
    )

    # 4. Save in memory using video ID
    video_stores[video_id] = vector_store

    return {
        "status": "processed",
        "chunks": len(chunks)
    }


def format_docs(retrieved_docs):
    """
    Combine retrieved documents into one context string.
    """

    return "\n\n".join(
        doc.page_content
        for doc in retrieved_docs
    )


def ask_question(video_id: str, question: str):
    """
    Retrieve relevant chunks and generate an answer
    using a custom LCEL RAG chain.
    """

    if video_id not in video_stores:
        raise ValueError(
            "Video not processed. Process the video first."
        )

    # 1. Get the video-specific vector store
    vector_store = video_stores[video_id]

    # 2. Create retriever
    retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 4}
    )

    # 3. Create parallel chain
    parallel_chain = RunnableParallel({
        "context": retriever | RunnableLambda(format_docs),
        "question": RunnablePassthrough()
    })

    # 4. Build complete RAG chain
    main_chain = (
        parallel_chain
        | prompt
        | llm
        | StrOutputParser()
    )

    # 5. Invoke chain
    answer = main_chain.invoke(question)

    return answer
