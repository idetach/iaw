import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useEffect, useRef } from 'react'
import {
  Box,
  Button,
  Flex,
  Spinner,
  Text,
  useToast,
} from '@chakra-ui/react'
import { useAppStore } from './store/useAppStore'
import { hasFirebaseConfig } from './lib/firebase'
import { watchAuth, logout } from './lib/auth'
import LoginPage from './pages/LoginPage'
import CasesPage from './pages/CasesPage'
import SettingsPage from './pages/SettingsPage'
import AccountPage from './pages/AccountPage'
import NewCasePage from './pages/NewCasePage'
import TopNav from './components/layout/TopNav'
import Sidebar from './components/layout/Sidebar'

function ProtectedLayout() {
  const selectedCaseId = useAppStore((s) => s.selectedCaseId)
  const location = useLocation()
  const showSidebar = location.pathname.startsWith('/cases')

  return (
    <Flex direction="column" minH="100vh" maxH="100vh" overflow="hidden">
      <TopNav />
      <Flex flex="1" minH="0" overflow="hidden">
        {showSidebar && <Sidebar />}
        <Box flex="1" p={{ base: 3, md: 4 }} overflowY="auto">
          <Routes>
            <Route path="/cases" element={<CasesPage />} />
            <Route path="/cases/new" element={<NewCasePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/account" element={<AccountPage />} />
            <Route path="*" element={<Navigate to={selectedCaseId ? `/cases?case=${selectedCaseId}` : '/cases'} replace />} />
          </Routes>
        </Box>
      </Flex>
    </Flex>
  )
}

export default function App() {
  const auth = useAppStore((s) => s.auth)
  const setAuthUser = useAppStore((s) => s.setAuthUser)
  const setAuthLoading = useAppStore((s) => s.setAuthLoading)
  const loadMeta = useAppStore((s) => s.loadMeta)
  const loadCases = useAppStore((s) => s.loadCases)
  const toast = useToast()
  const didBootstrapRef = useRef(false)

  useEffect(() => {
    if (didBootstrapRef.current) {
      return
    }
    didBootstrapRef.current = true
    loadMeta()
    loadCases()
  }, [loadMeta, loadCases])

  useEffect(() => {
    setAuthLoading(true)
    const unsub = watchAuth((user) => {
      setAuthUser(user)
    })
    return unsub
  }, [setAuthLoading, setAuthUser])

  if (auth.loading) {
    return (
      <Flex minH="100vh" align="center" justify="center" direction="column" gap={3}>
        <Spinner color="brand.yellow" />
        <Text color="gray.300">Initializing iawwai...</Text>
      </Flex>
    )
  }

  if (!hasFirebaseConfig && !auth.user) {
    return (
      <Flex minH="100vh" align="center" justify="center" p={6}>
        <Box
          maxW="520px"
          w="full"
          bg="brand.card"
          border="1px solid"
          borderColor="brand.border"
          borderRadius="14px"
          p={6}
        >
          <Text fontSize="xl" fontWeight="600" mb={2}>
            Firebase auth not configured
          </Text>
          <Text color="gray.300" mb={4}>
            Fill web_app/.env (from .env.example) to enable email and Google sign-in.
          </Text>
          <Button
            variant="action"
            onClick={() => {
              setAuthUser({ uid: 'local-dev', email: 'local@dev' })
              toast({ status: 'info', title: 'Entered local development mode' })
            }}
          >
            Continue in local mode
          </Button>
        </Box>
      </Flex>
    )
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={auth.user ? <Navigate to="/cases" replace /> : <LoginPage />}
      />
      <Route
        path="/*"
        element={auth.user ? <ProtectedLayout /> : <Navigate to="/login" replace />}
      />
      <Route path="/logout" element={<LogoutView />} />
    </Routes>
  )
}

function LogoutView() {
  const toast = useToast()
  useEffect(() => {
    logout()
      .catch((err) => {
        toast({ status: 'error', title: 'Logout failed', description: err.message })
      })
  }, [toast])
  return <Navigate to="/login" replace />
}
