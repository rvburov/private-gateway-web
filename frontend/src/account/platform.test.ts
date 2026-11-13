import { describe, expect, it } from 'vitest';
import { cardOrder, detectPlatform } from './platform';
import { agents } from '../test/agents';

describe('visitor platform from the User-Agent', () => {
  it('recognizes each desktop and mobile system', () => {
    expect(detectPlatform({ userAgent: agents.windows })).toBe('windows');
    expect(detectPlatform({ userAgent: agents.macos, maxTouchPoints: 0 })).toBe('macos');
    expect(detectPlatform({ userAgent: agents.iphone, maxTouchPoints: 5 })).toBe('ios');
    expect(detectPlatform({ userAgent: agents.ipad, maxTouchPoints: 5 })).toBe('ios');
    expect(detectPlatform({ userAgent: agents.linux })).toBe('linux');
  });
  it('never takes Android for Linux', () => {
    expect(agents.android).toContain('Linux');
    expect(detectPlatform({ userAgent: agents.android, maxTouchPoints: 5 })).toBe('android');
    expect(detectPlatform({ userAgent: agents.androidFirefox })).toBe('android');
  });
  it('takes a touch Mac for an iPad in desktop mode', () => {
    expect(detectPlatform({ userAgent: agents.macos, maxTouchPoints: 5 })).toBe('ios');
    expect(detectPlatform({ userAgent: agents.macos, maxTouchPoints: 1 })).toBe('macos');
  });
  it('uses the client hint when the User-Agent is empty', () => {
    expect(detectPlatform({ userAgent: '', userAgentData: { platform: 'Android' } })).toBe('android');
    expect(detectPlatform({ userAgent: '', userAgentData: { platform: 'Windows' } })).toBe('windows');
  });
  it('leaves unknown systems to the usual order', () => {
    expect(detectPlatform({ userAgent: agents.chromeos })).toBeNull();
    expect(detectPlatform({ userAgent: 'curl/8.0' })).toBeNull();
    expect(detectPlatform({ userAgent: '' })).toBeNull();
    expect(detectPlatform(undefined)).toBeNull();
  });
  it('puts the visitor platform first and keeps the rest in order', () => {
    expect(cardOrder(null)).toEqual(['windows', 'macos', 'linux', 'android']);
    expect(cardOrder('ios')).toEqual(['windows', 'macos', 'linux', 'android']);
    expect(cardOrder('android')).toEqual(['android', 'windows', 'macos', 'linux']);
    expect(cardOrder('linux')).toEqual(['linux', 'windows', 'macos', 'android']);
    expect(cardOrder('macos')).toEqual(['macos', 'windows', 'linux', 'android']);
  });
});
