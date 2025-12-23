// src/pages/AssistantChat.tsx
import React, { useState } from 'react'
import { api } from "../api/api";

type ChatMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
}

const AssistantChatPage: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 1,
      role: 'assistant',
      content: '哈囉，我是 EPS 生產排程小幫手，有什麼想查的都可以問我 👍',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSend = async () => {
    const q = input.trim()
    if (!q || loading) return

    setError(null)

    // 使用者訊息先顯示
    const userMsg: ChatMessage = {
      id: Date.now(),
      role: 'user',
      content: q,
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.chat(q)
      const answerText = res?.answer ?? '（沒有收到回應內容）'

      const botMsg: ChatMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: answerText,
      }
      setMessages(prev => [...prev, botMsg])
    } catch (e: any) {
      console.error(e)
      setError(e?.message ?? '發生錯誤，請稍後再試一次')
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown: React.KeyboardEventHandler<HTMLTextAreaElement> = e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-page line-style">
      {/* 上方標題列（像聊天室標題） */}
      <header className="chat-header">
        <div className="chat-header-title">🤖 智能排程小幫手</div>
      </header>

      {/* 三行簡短提示 */}
      <div className="chat-hints compact">
        <div>・輸入完整訂單編號，例如：<code>20240401001</code></div>
        <div>・可以問：<code>幫我查訂單 20240401001 的生產進度</code></div>
        <div>・也可以問：<code>目前有哪些未完成的訂單？</code></div>
      </div>

      {/* 聊天主體 */}
      <div className="chat-window">
        <div className="chat-messages">
          {messages.map(msg => (
            <div
              key={msg.id}
              className={`chat-row ${
                msg.role === 'user' ? 'chat-row-user' : 'chat-row-assistant'
              }`}
            >
              {msg.role === 'assistant' && (
                <div className="chat-avatar">🤖</div>
              )}

              <div
                className={`chat-bubble ${
                  msg.role === 'user' ? 'bubble-user' : 'bubble-assistant'
                }`}
              >
                {msg.content.split('\n').map((line, idx) => (
                  <p key={idx}>{line}</p>
                ))}
              </div>
            </div>
          ))}

          {loading && (
            <div className="chat-row chat-row-assistant">
              <div className="chat-avatar">🤖</div>
              <div className="chat-bubble bubble-assistant typing-bubble">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </div>
            </div>
          )}
        </div>

        {error && <div className="chat-error">❌ {error}</div>}

        {/* 下方輸入區（像 LINE 底部） */}
        <div className="chat-input-bar">
          <textarea
            className="chat-input"
            placeholder="輸入想問的排程 / 訂單 / 報工，按 Enter 送出（Shift+Enter 換行）"
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            className="chat-send-btn"
            onClick={handleSend}
            disabled={loading || !input.trim()}
          >
            送出
          </button>
        </div>
      </div>
    </div>
  )
}

export default AssistantChatPage
