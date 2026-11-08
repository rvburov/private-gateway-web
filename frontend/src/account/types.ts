import type { User } from '../api/types';

export type { User };
export interface ListResult<T> { items: T[]; total: number }
export interface Invite {
  id: number;
  email: string;
  role: 'admin' | 'member';
  created_at: string;
  expires_at: string;
  used_at: string | null;
  revoked_at: string | null;
}
export type InviteStatus = 'active' | 'used' | 'revoked' | 'expired';
export type Platform = 'windows' | 'macos' | 'ios' | 'linux' | 'android';
export interface Download {
  platform: Platform;
  available: boolean;
  version: string | null;
  filename: string | null;
  size_bytes: number | null;
  sha256: string | null;
  url: string | null;
}

// Адаптация функций AI Agent Capper: источник указан в реестре переноса.
export function personName(user: Pick<User, 'display_name' | 'email'>): string {
  return user.display_name.trim() || user.email;
}
export function looksLikeEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value);
}
export function inviteStatus(invite: Invite, now = Date.now()): InviteStatus {
  if (invite.used_at) return 'used';
  if (invite.revoked_at) return 'revoked';
  return new Date(invite.expires_at).getTime() <= now ? 'expired' : 'active';
}
export function safeDownloadUrl(download: Download): string | null {
  if (!download.available || !download.url) return null;
  if (download.platform !== 'ios') {
    return download.url === `/api/downloads/${download.platform}/file` ? download.url : null;
  }
  try {
    const url = new URL(download.url);
    return url.protocol === 'https:' && url.hostname === 'apps.apple.com' && !url.username && !url.password
      ? url.href : null;
  } catch { return null; }
}
