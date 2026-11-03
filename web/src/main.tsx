import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import Gallery from './Gallery.tsx'

const pathname = window.location.pathname.replace(/\/+$/, '')
const isGallery = pathname === '/gallery'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isGallery ? <Gallery /> : <App />}
  </StrictMode>,
)
