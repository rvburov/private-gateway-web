import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientPreview } from './ClientPreview';

let language: 'en' | 'ru' = 'en';
vi.mock('../app/context', () => ({ useApp: () => ({ lang: language }) }));

function message(frame: HTMLIFrameElement, data: unknown, source: Window | null = frame.contentWindow) {
  fireEvent(window, new MessageEvent('message', { source, origin: window.location.origin, data }));
}

describe('persistent client preview', () => {
  beforeEach(() => { language = 'en'; });

  it('changes device and language inside the same iframe and rejects stale replies', () => {
    const { rerender } = render(<ClientPreview />);
    const frame = screen.getByTitle(/Interactive Private Gateway/) as HTMLIFrameElement;
    const originalSource = frame.src;
    const send = vi.spyOn(frame.contentWindow!, 'postMessage');
    message(frame, { type: 'pg-client-ready' });
    const initial = send.mock.calls.at(-1)![0];
    fireEvent.click(screen.getByRole('button', { name: 'Phone' }));
    const phone = send.mock.calls.at(-1)![0];
    expect(phone.device).toBe('android');
    expect(phone.requestId).toBeGreaterThan(initial.requestId);
    message(frame, { type: 'pg-client-state', requestId: phone.requestId, device: 'android', language: 'en', board: '01-main.html' });
    message(frame, { type: 'pg-client-state', requestId: initial.requestId, device: 'windows', language: 'en', board: '01-main.html' });
    expect(frame.dataset.device).toBe('android');
    language = 'ru';
    rerender(<ClientPreview />);
    expect(screen.getByTitle(/Интерактивный макет/)).toBe(frame);
    expect(frame.src).toBe(originalSource);
    expect(send.mock.calls.at(-1)![0]).toMatchObject({ device: 'android', language: 'ru' });
  });

  it('ignores messages from windows other than its own client', () => {
    render(<ClientPreview />);
    const frame = screen.getByTitle(/Interactive Private Gateway/) as HTMLIFrameElement;
    const send = vi.spyOn(frame.contentWindow!, 'postMessage');
    message(frame, { type: 'pg-client-ready' }, window);
    expect(send).not.toHaveBeenCalled();
  });
});
