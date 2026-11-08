import { Link } from 'react-router';
import { useApp } from '../app/context';
import { iconPaths } from './icon-paths';
import { brandPaths } from './brand-paths';

export function Icon({ name, className = '' }: { name: string; className?: string }) {
  const brand = brandPaths[name];
  if (brand) return <svg className={`platform-mark ${className}`} viewBox={brand.viewBox} fill="currentColor" stroke="none" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: brand.body }} />;
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: iconPaths[name] ?? iconPaths.shield }} />;
}

export function Brand() {
  return <Link className="brand" to="/" aria-label="Private Gateway Web"><img src="/assets/logo.svg" alt="" /><span><strong>Private Gateway</strong><small>WEB · CLIENT DOWNLOADS</small></span></Link>;
}

export function LanguageSwitch() {
  const { lang, setLanguage } = useApp();
  return <div className="language-switch segmented-control" role="group" aria-label={lang === 'ru' ? 'Язык интерфейса' : 'Interface language'}>
    <button type="button" lang="en" aria-label="English" aria-pressed={lang === 'en'} onClick={() => setLanguage('en')}>EN</button>
    <button type="button" lang="ru" aria-label="Русский" aria-pressed={lang === 'ru'} onClick={() => setLanguage('ru')}>RU</button>
  </div>;
}

export function ThemeButton() {
  const { lang, theme, toggleTheme } = useApp();
  const label = lang === 'ru' ? (theme === 'dark' ? 'Включить светлую тему' : 'Включить темную тему') : (theme === 'dark' ? 'Use light theme' : 'Use dark theme');
  return <button type="button" className="theme-btn appearance-button" aria-label={label} title={label} aria-pressed={theme === 'dark'} onClick={toggleTheme}><Icon name="appearance" /></button>;
}
