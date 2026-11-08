export interface User {
  id: number;
  email: string;
  display_name: string;
  role: 'admin' | 'member';
  status: 'active' | 'blocked';
  totp_enabled: boolean;
  created_at: string;
}

export interface LoginResult {
  status: 'ok' | 'totp_required' | 'totp_setup_required';
  user: User | null;
}
