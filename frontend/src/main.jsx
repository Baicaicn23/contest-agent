import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles/tokens.css'
import './styles/app.css'

// 整个前端的入口：把 <App> 挂到 index.html 的 #root 节点上。
// 类比后端：这就是 main()，前面加载的两个 css 是全局配置。
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
