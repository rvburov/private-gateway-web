import { Link } from 'react-router';
import { useApp } from '../app/context';
import { Brand, Icon } from '../ui';
import { ClientPreview } from './ClientPreview';
import { landingText } from './locales';

export function LandingPage() {
  const { lang, user } = useApp();
  const text = landingText[lang];
  return <main className="landing">
    <section className="container hero">
      <div className="hero-copy"><div className="hero-intro"><span className="dot" />Private Gateway Client</div>
        <h1>{text.title}<span>{text.highlight}</span></h1>
        <p className="hero-desc">{text.description}</p>
        <div className="hero-download"><div className="hero-actions"><Link className="btn primary lg" to={user ? '/downloads' : '/login'}><Icon name="download" /><span>{text.download}</span></Link></div>
          <p className="hero-note">{text.invite}</p>
          <div className="platforms">{[['windows', 'Windows'], ['apple', 'macOS'], ['apple', 'iOS'], ['linux', 'Linux'], ['android', 'Android']].map(([icon, name]) => <span key={name} data-platform={name.toLowerCase()}><Icon name={icon} />{name}</span>)}</div>
        </div>
        <p className="hero-boundary">{text.boundary}<br />{text.boundaryMore}</p>
      </div>
      <ClientPreview />
    </section>
    <div className="container"><div className="protocol-strip"><span>{text.protocols}</span><div className="protocols"><span>VLESS + REALITY</span><span>Hysteria2</span><span>WireGuard</span></div></div></div>
    <footer className="footer"><div className="container footer-inner"><Brand /><div className="footer-links"><Link to={user ? '/downloads' : '/login'}>{user ? text.account : text.signIn}</Link><Link to="/register">{text.invitation}</Link></div><p>{text.footer}</p></div></footer>
  </main>;
}
