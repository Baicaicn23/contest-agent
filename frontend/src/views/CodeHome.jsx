import Logo from '../components/Logo.jsx'
import ChatInput from '../components/ChatInput.jsx'
import UsageCard from '../components/UsageCard.jsx'

// 工作台首页（截图 1）：问候语 + Overview 用量卡 + 底部输入框。
// 在首页发消息 = 开一个新聊天会话并把这句话发出去（由 App 的 onOpenChat 完成）。
export default function CodeHome({ userName, onOpenChat }) {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <div className="greeting">
          <Logo size={32} />
          <h1>接下来做什么，{userName}？</h1>
        </div>
        <UsageCard />
      </div>
      <ChatInput
        placeholder="描述任务或提问，/ 唤起命令"
        onSend={(text) => onOpenChat(text)}
        onCommandResult={(cmd, result, original) => onOpenChat(original || cmd.cmd, result)}
      />
    </div>
  )
}
