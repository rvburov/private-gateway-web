import type { Platform } from './types';

/** Только то, что нужно из navigator: так функцию легко проверить без браузера. */
export interface NavigatorLike {
  userAgent?: string;
  maxTouchPoints?: number;
  userAgentData?: { platform?: string };
}

/**
 * Система посетителя по User-Agent (DECISIONS п. 11). Android проверяется раньше Linux:
 * в его User-Agent есть «Linux». iPadOS в режиме «как на компьютере» называет себя
 * Macintosh, но у Mac нет сенсорного экрана — Mac с касаниями считается iPad.
 * Неизвестная система (ChromeOS, боты) — null: порядок карточек остается прежним.
 */
export function detectPlatform(nav: NavigatorLike | undefined): Platform | null {
  if (!nav) return null;
  const agent = nav.userAgent ?? '';
  const hint = nav.userAgentData?.platform ?? '';
  if (/Android/i.test(agent) || /^Android$/i.test(hint)) return 'android';
  if (/iPhone|iPad|iPod/i.test(agent)) return 'ios';
  if (/Macintosh|Mac OS X/i.test(agent) || /^macOS$/i.test(hint)) return (nav.maxTouchPoints ?? 0) > 1 ? 'ios' : 'macos';
  if (/Windows/i.test(agent) || /^Windows$/i.test(hint)) return 'windows';
  if (/CrOS/i.test(agent) || /^Chrome OS$/i.test(hint)) return null;
  if (/Linux|X11/i.test(agent) || /^Linux$/i.test(hint)) return 'linux';
  return null;
}

export const DESKTOP_ORDER: readonly Platform[] = ['windows', 'macos', 'linux', 'android'];

/** Карточки с файлами: система посетителя первой, остальные в прежнем порядке. iOS — отдельный блок. */
export function cardOrder(detected: Platform | null): Platform[] {
  if (!detected || detected === 'ios') return [...DESKTOP_ORDER];
  return [detected, ...DESKTOP_ORDER.filter((platform) => platform !== detected)];
}
