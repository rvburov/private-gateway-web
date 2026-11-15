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
export type MacArchitecture = 'arm64' | 'x64';
export interface Download {
  platform: Platform;
  available: boolean;
  version: string | null;
  filename: string | null;
  size_bytes: number | null;
  sha256: string | null;
  url: string | null;
  architecture?: MacArchitecture;
  variants?: DownloadVariant[] | null;
}
export type DownloadVariant = Omit<Download, 'platform' | 'variants' | 'architecture'> & { architecture: MacArchitecture };

export interface SiteSession {
  id: number;
  label: string;
  ip_masked: string | null;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}
export interface AppDeviceInfo {
  id: number;
  name: string;
  platform: Platform;
  app_version: string;
  ip_masked: string | null;
  created_at: string;
  last_seen_at: string;
}
export interface DevicesInfo {
  sessions: SiteSession[];
  devices: AppDeviceInfo[];
  session_limit: number;
  device_limit: number;
  // Новые установки приложения за окно смены устройств (DECISIONS п. 11)
  device_changes: { used: number; limit: number; days: number };
}
export interface DownloadEvent {
  id: number;
  at: string;
  platform: Platform;
  version: string;
  filename: string | null;
  ip_masked: string | null;
  device: string;
  user: { id: number; email: string; display_name: string } | null;
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
    const endpoint = `/api/downloads/${download.platform}/file`;
    if (download.architecture !== undefined) {
      if (download.platform !== 'macos') return null;
      if (download.architecture === 'x64') return download.url === `${endpoint}?architecture=x64` ? download.url : null;
      if (download.architecture !== 'arm64') return null;
    }
    return download.url === endpoint ? download.url : null;
  }
  try {
    const url = new URL(download.url);
    return url.protocol === 'https:' && url.hostname === 'apps.apple.com' && !url.username && !url.password
      ? url.href : null;
  } catch { return null; }
}
