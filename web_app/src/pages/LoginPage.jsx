import { useState } from 'react'
import {
  Box,
  Button,
  Divider,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Stack,
  Text,
  useToast,
} from '@chakra-ui/react'
import { loginWithEmail, loginWithGoogle, triggerPasswordReset } from '../lib/auth'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const toast = useToast()

  const onEmailLogin = async () => {
    setLoading(true)
    try {
      await loginWithEmail(email, password)
      toast({ status: 'success', title: 'Signed in' })
    } catch (error) {
      toast({ status: 'error', title: 'Sign-in failed', description: error.message })
    } finally {
      setLoading(false)
    }
  }

  const onGoogleLogin = async () => {
    setLoading(true)
    try {
      await loginWithGoogle()
      toast({ status: 'success', title: 'Google sign-in successful' })
    } catch (error) {
      toast({ status: 'error', title: 'Google sign-in failed', description: error.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <Box minH="100vh" display="grid" placeItems="center" px={4}>
      <Box
        w="full"
        maxW="440px"
        bg="brand.card"
        border="1px solid"
        borderColor="brand.border"
        borderRadius="16px"
        boxShadow="0 10px 20px rgba(0,0,0,0.4)"
        p={6}
      >
        <Heading size="lg" mb={1}>
          iawwai sign in
        </Heading>
        <Text color="gray.400" mb={6}>
          Email/password now, Firebase auth providers later.
        </Text>

        <Stack spacing={4}>
          <FormControl>
            <FormLabel fontSize="sm" color="gray.400">
              Email
            </FormLabel>
            <Input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              bg="#101010"
              borderColor="brand.border"
            />
          </FormControl>

          <FormControl>
            <FormLabel fontSize="sm" color="gray.400">
              Password
            </FormLabel>
            <Input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              bg="#101010"
              borderColor="brand.border"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  onEmailLogin()
                }
              }}
            />
          </FormControl>

          <Button variant="action" onClick={onEmailLogin} isLoading={loading}>
            sign in
          </Button>

          <Button
            variant="ghostline"
            onClick={async () => {
              try {
                await triggerPasswordReset(email)
                toast({ status: 'info', title: 'Password reset email sent' })
              } catch (error) {
                toast({ status: 'error', title: 'Reset failed', description: error.message })
              }
            }}
          >
            forgot password
          </Button>

          <Divider borderColor="brand.border" />

          <Button variant="ghostline" onClick={onGoogleLogin} isLoading={loading}>
            continue with Google
          </Button>
        </Stack>
      </Box>
    </Box>
  )
}
