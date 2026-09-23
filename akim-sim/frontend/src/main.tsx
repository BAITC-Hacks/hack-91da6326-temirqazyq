import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import './index.css'
import App from './App.tsx'
import { antdTheme } from './theme'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider theme={antdTheme} locale={ruRU}>
      <App />
    </ConfigProvider>
  </StrictMode>,
)
