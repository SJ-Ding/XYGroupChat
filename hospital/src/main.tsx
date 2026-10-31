import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { loadState, APP_BASE, HOSPITAL_NAME, ACTIVE_HOSPITAL } from './data';
import './index.css';

const root = ReactDOM.createRoot(document.getElementById('root')!);

function render() {
  root.render(
    <React.StrictMode>
      <BrowserRouter basename={APP_BASE}>
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  );
}

// Every hospital bootstraps from its own scoped API.
root.render(<div style={{ padding: 48, textAlign: 'center', color: '#64748B' }}>正在连接附近两家医院预约平台…</div>);
async function bootstrap() {
  // Preserve existing payment and result links without opening the wrong app.
  const legacy = location.pathname.match(/^\/hospital\/(pay|appointment\/result)\/([^/]+)/);
  if (!ACTIVE_HOSPITAL && legacy) {
    const response = await fetch('/api/hospital/appointments/' + encodeURIComponent(legacy[2]));
    if (response.ok) {
      const appointment = await response.json();
      if (appointment.hospitalId && appointment.hospitalId !== 'legacy-hospital') {
        location.replace(`/hospital/apps/${appointment.hospitalId}/${legacy[1]}/${legacy[2]}${location.search}`);
        return;
      }
    }
  }
  await loadState();
  document.title = HOSPITAL_NAME + ' · 模拟挂号';
  render();
}
bootstrap().catch(() => root.render(<div style={{ padding: 48 }}>医院服务暂不可用，请刷新重试。<a href="/hospital/">返回医院选择</a></div>));
