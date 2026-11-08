import { useEffect, useRef, useState } from 'react';
import { useApp } from '../app/context';
import { Icon } from '../ui';
import { landingText } from './locales';

type Device = 'windows' | 'android';
interface Command {
  type: 'pg-client-command';
  requestId: number;
  device: Device;
  language: 'en' | 'ru';
  board: string;
}

export function ClientPreview() {
  const { lang } = useApp();
  const text = landingText[lang];
  const [device, setDevice] = useState<Device>(() => window.matchMedia('(max-width:760px)').matches ? 'android' : 'windows');
  const frame = useRef<HTMLIFrameElement>(null);
  const ready = useRef(false);
  const pending = useRef<Command>({ type: 'pg-client-command', requestId: 1, device, language: lang, board: '01-main.html' });
  // Адрес не меняется при выборе устройства или языка: документ клиента остается одним.
  const [source] = useState(() => `/client/runtime.html?device=${device}&board=01-main.html&language=${lang}&thumb=1&embed=1`);

  useEffect(() => {
    function receive(event: MessageEvent) {
      const element = frame.current;
      if (!element || event.source !== element.contentWindow || event.origin !== window.location.origin) return;
      const message: unknown = event.data;
      if (!message || typeof message !== 'object' || !('type' in message)) return;
      if (message.type === 'pg-client-ready') {
        ready.current = true;
        element.contentWindow?.postMessage(pending.current, window.location.origin);
      }
      if (message.type === 'pg-client-state' && 'requestId' in message && message.requestId === pending.current.requestId) {
        const data = message as Record<string, unknown>;
        if (typeof data.board === 'string' && /^[\w-]+\.html$/.test(data.board)) {
          pending.current.board = data.board;
          element.dataset.board = data.board;
        }
        if (data.device === 'windows' || data.device === 'android') element.dataset.device = data.device;
        if (data.language === 'en' || data.language === 'ru') element.dataset.language = data.language;
        if (typeof data.documentId === 'string') element.dataset.documentId = data.documentId;
        element.dataset.ready = 'true';
      }
    }
    window.addEventListener('message', receive);
    return () => { window.removeEventListener('message', receive); ready.current = false; };
  }, []);

  useEffect(() => {
    pending.current = { ...pending.current, requestId: pending.current.requestId + 1, device, language: lang };
    if (ready.current) frame.current?.contentWindow?.postMessage(pending.current, window.location.origin);
  }, [device, lang]);

  return <div className="hero-visual" id="try-client">
    <div className="demo-toolbar"><span className="eyebrow"><span className="dot" />{text.preview}</span>
      <div className="device-switch segmented-control" role="group" aria-label={text.device}>
        <button type="button" data-device="windows" aria-pressed={device === 'windows'} onClick={() => setDevice('windows')}><Icon name="monitor" />{text.computer}</button>
        <button type="button" data-device="android" aria-pressed={device === 'android'} onClick={() => setDevice('android')}><Icon name="phone" />{text.phone}</button>
      </div>
    </div>
    <iframe ref={frame} id="client-demo" className={`client-demo${device === 'android' ? ' phone' : ''}`} title={text.frameTitle} src={source} sandbox="allow-scripts allow-same-origin" loading="eager" />
    <p className="demo-caption"><Icon name="eye" /><span>{text.hint}<br />{text.hintMore}</span></p>
  </div>;
}
