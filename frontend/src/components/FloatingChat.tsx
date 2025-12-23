import React, { useState, useRef, useEffect } from 'react'
import { api } from '../api/api'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export default function FloatingChat() {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // 監聽來自外部的消息（如排程完成通知）
  useEffect(() => {
    const handleExternalMessage = (event: CustomEvent<{ message: string; autoOpen?: boolean }>) => {
      const assistantMessage: Message = {
        role: 'assistant',
        content: event.detail.message
      }
      setMessages(prev => [...prev, assistantMessage])
      
      // 如果指定自動打開，則打開聊天窗口
      if (event.detail.autoOpen) {
        setIsOpen(true)
      }
    }

    window.addEventListener('floatingChatMessage' as any, handleExternalMessage)
    return () => {
      window.removeEventListener('floatingChatMessage' as any, handleExternalMessage)
    }
  }, [])

  const handleSend = async () => {
    if (!input.trim() || loading) return

    const userMessage: Message = { role: 'user', content: input }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      const response = await api.chat(input)
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer
      }
      setMessages(prev => [...prev, assistantMessage])
    } catch (error) {
      const errorMessage: Message = {
        role: 'assistant',
        content: '抱歉，發生錯誤，請稍後再試。'
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!isOpen) {
    return (
      <button
        className="floating-chat-button"
        onClick={() => setIsOpen(true)}
        title="打開聊天助理"
      >
        💬
      </button>
    )
  }

  return (
    <div className="floating-chat-container">
      <div className="floating-chat-header">
        <span>🤖 AI 助理</span>
        <button
          className="floating-chat-close"
          onClick={() => setIsOpen(false)}
          title="關閉"
        >
          ✕
        </button>
      </div>

      <div className="floating-chat-messages">
        {messages.length === 0 && (
          <div className="floating-chat-welcome">
            👋 您好！我是生產排程系統的 AI 助理，有什麼可以幫您的嗎？
          </div>
        )}
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`floating-chat-message ${msg.role}`}
          >
            {msg.content}
          </div>
        ))}
        {loading && (
          <div className="floating-chat-message assistant loading">
            思考中...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="floating-chat-input-bar">
        <textarea
          className="floating-chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="輸入訊息..."
          rows={1}
          disabled={loading}
        />
        <button
          className="floating-chat-send"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          ➤
        </button>
      </div>
    </div>
  )
}
