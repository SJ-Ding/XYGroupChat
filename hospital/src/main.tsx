import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { loadState } from './data';
import './index.css';

const root = ReactDOM.createRoot(document.getElementById('root')!);

function render() {
  root.render(
    <React.StrictMode>
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  );
}

// 号源与预约来自后端；加载失败时仍渲染页面（显示无号），不阻塞浏览。
root.render(<div style={{ padding: 48, textAlign: 'center', color: '#64748B' }}>正在连接附近两家医院预约平台…</div>);
loadState().catch(() => undefined).finally(render);
