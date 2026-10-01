import ChatInput from '../components/ChatInput.jsx'

// Codex 式首页（M9 精简版）：云图标 + 大问题 + 底部输入卡，仅此三样。
// 截止临近 / 点子列表 / chips 行 / under-chips 全部移除（用户要求保持简洁）；
// 模型/权限/上下文全部收进输入卡（见 ChatInput）。
// 项目 chip 的归属功能随 chips 行移除——归属改在聊天里按需绑定（M5 的 /api 绑定保留）。
export default function HomeView({ userName, project, onProjectChange, branch,
                                   accessFull, onToggleAccess, modelLabel,
                                   onSend, onCommand, onCommandResult,
                                   className = '', permissionMode, onPermissionChange,
                                   models, activeModel, onModelChange }) {
  return (
    <div className={`home-root ${className}`}>
      <div className="home-scroll">
        <div className="home-hero">
          <div className="cloud-icon">
            <span className="cloud-glyph">{'>_'}</span>
          </div>
          <h1 className="hero-question">
            你想让我们在 <span className="hero-project">{project ? project.name : '比赛情报'}</span> 中构建什么？
          </h1>
        </div>
      </div>

      <div className="composer-wrap center">
        <ChatInput
          centered
          placeholder="随心输入"
          onSend={(text) => onSend(text, project)}
          onCommandResult={(cmd, result, original) =>
            onCommandResult?.(original || cmd.cmd, result)}
          permissionMode={permissionMode}
          onPermissionChange={onPermissionChange}
          models={models}
          activeModel={activeModel}
          onModelChange={onModelChange}
        />
      </div>
    </div>
  )
}
