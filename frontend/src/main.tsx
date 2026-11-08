import './styles/style.css';
import './styles/auth.css';
import './styles/account.css';
import './styles/application.css';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { App } from './app/App';
import { AppProvider } from './app/context';

createRoot(document.getElementById('root')!).render(<BrowserRouter><AppProvider><App /></AppProvider></BrowserRouter>);
