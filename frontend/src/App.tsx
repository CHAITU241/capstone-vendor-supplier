import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { SupplierIntakePage } from './pages/SupplierIntakePage'
import { SupplierReviewPage } from './pages/SupplierReviewPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="suppliers/new" element={<SupplierIntakePage />} />
        <Route path="suppliers/:supplierId" element={<SupplierReviewPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

