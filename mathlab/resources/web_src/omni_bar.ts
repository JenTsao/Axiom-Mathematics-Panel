// omni_bar.ts — MathLab OmniBar 前端 (Vanilla TypeScript)
//
// 与 PySide6 通过 QWebChannel 进行双向通信：
//   JS  -> Python :  backend.submit(text)         回车提交
//                    backend.request_dismiss()     Esc 请求关闭
//   Python -> JS  :  window.omni.focusInput()      聚焦输入框
//                    window.omni.setValue(text)    清空/回填
//                    window.omni.setStatus(s)       更新状态微标
//                    window.omni.setAgent(a)        更新 Agent 图标

// qwebchannel.js 注入的全局对象（无类型声明，这里用 any 兜底）
declare const QWebChannel: any;
declare const qt: any;

interface OmniBackend {
  submit(text: string): void;
  request_dismiss(): void;
}

let backend: OmniBackend | null = null;
let inputEl: HTMLInputElement | null = null;
let statusEl: HTMLElement | null = null;
let agentEl: HTMLElement | null = null;

function initDom(): void {
  inputEl = document.getElementById("omni-input") as HTMLInputElement | null;
  statusEl = document.getElementById("omni-status");
  agentEl = document.getElementById("omni-agent");

  if (inputEl) {
    inputEl.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        if (backend && inputEl) backend.submit(inputEl.value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        if (backend) backend.request_dismiss();
      }
    });
  }

  // 暴露给 Python (PySide6 runJavaScript) 调用的接口
  (window as any).omni = {
    focusInput(): void {
      if (inputEl) {
        inputEl.focus();
        inputEl.select();
      }
    },
    setValue(text: string): void {
      if (inputEl) inputEl.value = text;
    },
    setStatus(s: string): void {
      if (statusEl) statusEl.textContent = s;
    },
    setAgent(a: string): void {
      if (agentEl) agentEl.textContent = a;
    },
  };
}

window.onload = function (): void {
  initDom();

  if (typeof qt !== "undefined" && qt.webChannelTransport) {
    // 建立与 Python 后端的双向通道
    new QWebChannel(qt.webChannelTransport, function (channel: any): void {
      backend = channel.objects.backend as OmniBackend;
    });
  } else {
    console.warn("[OmniBar] 未检测到 Qt WebChannel，处于纯前端预览模式。");
  }
};
