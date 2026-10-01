import ChatInput from '../components/ChatInput.jsx'

// Codex 式首页（M9 精简版）：云图标 + 大问题 + 输入卡，**作为一组垂直居中**。
// 截止临近 / 点子列表 / chips 行 / under-chips 全部移除（用户要求保持简洁）；
// 模型/权限/上下文全部收进输入卡（见 ChatInput）。
export default function HomeView({ userName, project, onProjectChange, branch,
                                   accessFull, onToggleAccess, modelLabel,
                                   onSend, onCommand, onCommandResult,
                                   className = '', permissionMode, onPermissionChange,
                                   models, activeModel, onModelChange }) {
  return (
    <div className={`home-root ${className}`}>
      <div className="home-center">
        <div className="home-hero">
          <div className="cloud-icon">
            <span className="cloud-glyph">{'>_'}</span>
          </div>
          <h1 className="hero-question">
            你想让我们在 <span className="hero-project">{project ? project.name : '比赛情报'}</span> 中构建什么？
          </h1>
        </div>
        {/* ChatInput 自带 composer-wrap（含居中定位），这里不再包一层 */}
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
