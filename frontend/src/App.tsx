import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import { AppShell } from './components/AppShell'
import { HomePage } from './pages/HomePage'
import { SupplierLoginPage } from './pages/SupplierLoginPage'
import { SupplierApplicationPage } from './pages/SupplierApplicationPage'
import { DashboardPage } from './pages/DashboardPage'
import { SupplierReviewPage } from './pages/SupplierReviewPage'
import { AdminLoginPage } from './pages/AdminLoginPage'
import { AdminDashboardPage } from './pages/AdminDashboardPage'
import { ErpRecordsPage } from './pages/ErpRecordsPage'

function RequireRole({ role, children }: { role: 'supplier' | 'reviewer' | 'admin'; children: React.ReactNode }) {
  const { session } = useAuth()
  return session?.role === role ? children : <Navigate to={role === 'supplier' ? '/supplier/login' : '/'} replace />
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="supplier/login" element={<SupplierLoginPage />} />
        <Route path="admin/login" element={<AdminLoginPage />} />
        <Route path="admin" element={<RequireRole role="admin"><AdminDashboardPage /></RequireRole>} />
        <Route path="supplier/application" element={<RequireRole role="supplier"><SupplierApplicationPage /></RequireRole>} />
        <Route path="review" element={<RequireRole role="reviewer"><DashboardPage /></RequireRole>} />
        <Route path="review/erp" element={<RequireRole role="reviewer"><ErpRecordsPage /></RequireRole>} />
        <Route path="review/suppliers/:supplierId" element={<RequireRole role="reviewer"><SupplierReviewPage /></RequireRole>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
