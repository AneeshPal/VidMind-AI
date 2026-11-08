
import './App.css'

function App() {
  return (
    <div className="app">
      <header className="header">
        <div className="logo">V</div>

        <div>
          <h2>VidMind</h2>
          <p>Your AI video assistant</p>
        </div>
      </header>

      <main className="content">
        <div className="welcome-icon">✦</div>

        <h1>Understand every video.</h1>

        <p className="description">
          Ask questions, explore concepts, and
          summarize YouTube videos with AI.
        </p>

        <div className="status">
          <span className="status-dot"></span>
          Extension is running
        </div>

        <div className="empty-state">
          <p>Your video assistant is ready.</p>
          <span>
            Open a YouTube video to get started.
          </span>
        </div>
      </main>
    </div>
  )
}

export default App
