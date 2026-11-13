import { ApiError } from './client';

const errors: Record<string, [string, string]> = {
  invalid_credentials: ['Email or password is incorrect.', 'Неверный email или пароль.'],
  invalid_code: ['The code is invalid or has already been used. Wait for the next code and try again.', 'Код неверен или уже использован. Дождитесь следующего кода и повторите попытку.'],
  invalid_invite: ['This invitation is invalid, expired, or belongs to a different email.', 'Приглашение недействительно, истекло или выдано на другой email.'],
  invalid_reset: ['The reset code is invalid or expired.', 'Код сброса недействителен или истек.'],
  rate_limited: ['Too many attempts. Please wait before trying again.', 'Слишком много попыток. Подождите перед следующей попыткой.'],
  password_too_short: ['Use at least 12 characters.', 'Используйте не менее 12 символов.'],
  password_too_long: ['Use no more than 128 characters.', 'Используйте не более 128 символов.'],
  account_exists: ['This account already exists.', 'Такой аккаунт уже существует.'],
  login_expired: ['Your sign-in step expired. Enter your password again.', 'Шаг входа истек. Введите пароль заново.'],
  unauthorized: ['Your session ended. Please sign in again.', 'Сеанс завершен. Войдите заново.'],
  forbidden: ['You do not have access to this action.', 'У вас нет доступа к этому действию.'],
  csrf_failed: ['The request could not be confirmed. Please try again.', 'Не удалось подтвердить запрос. Повторите действие.'],
  validation_error: ['Check the entered values.', 'Проверьте введенные значения.'],
  busy: ['The service is busy. Please try again.', 'Сервис занят. Повторите попытку.'],
  not_found: ['This item is no longer available.', 'Этот объект больше недоступен.'],
  self_change_forbidden: ['You cannot revoke your own administrator access.', 'Нельзя отозвать собственный доступ администратора.'],
  last_admin: ['At least one active administrator is required.', 'Должен остаться хотя бы один активный администратор.'],
  no_changes: ['Nothing to change.', 'Нет изменений для сохранения.'],
  already_configured: ['Two-factor authentication is already enabled.', 'Двухфакторная аутентификация уже включена.'],
  setup_required: ['Set up two-factor authentication to continue.', 'Настройте двухфакторную аутентификацию для продолжения.'],
  code_required: ['Enter the code from your authenticator app.', 'Введите код из приложения-аутентификатора.'],
  invalid_password: ['The current password is incorrect.', 'Текущий пароль неверен.'],
  password_changed: ['The password has already been changed in another window. Reload the page.', 'Пароль уже изменен в другом окне. Обновите страницу.'],
  device_limit: ['All device places are taken. Remove a device to free a place.', 'Все места для устройств заняты. Удалите устройство, чтобы освободить место.'],
  device_change_limit: ['Too many new devices recently. Try later or ask the administrator.', 'Слишком много новых устройств за последнее время. Попробуйте позже или обратитесь к администратору.'],
  network_error: ['Cannot reach the service. Check your connection and retry.', 'Не удалось связаться с сервисом. Проверьте соединение и повторите попытку.'],
  server_error: ['The service is temporarily unavailable. Try again later.', 'Сервис временно недоступен. Повторите попытку позже.'],
};

export function errorText(error: unknown, lang: 'en' | 'ru'): string {
  const code = error instanceof ApiError ? error.code : 'network_error';
  return (errors[code] ?? errors.server_error)[lang === 'ru' ? 1 : 0];
}
