import { Box, Button, Heading, Text, useToast, VStack } from '@chakra-ui/react'
import { useAppStore } from '../store/useAppStore'
import { triggerPasswordReset } from '../lib/auth'

export default function AccountPage() {
  const user = useAppStore((s) => s.auth.user)
  const toast = useToast()

  return (
    <VStack align="stretch" spacing={4}>
      <Heading size="md">Account</Heading>

      <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>
        <Text color="gray.300" mb={4}>
          Signed in as {user?.email || 'unknown user'}
        </Text>

        <Button
          variant="action"
          onClick={async () => {
            try {
              await triggerPasswordReset(user?.email)
              toast({ status: 'success', title: 'Password reset email sent' })
            } catch (error) {
              toast({ status: 'error', title: 'Reset failed', description: error.message })
            }
          }}
        >
          change password
        </Button>
      </Box>
    </VStack>
  )
}
