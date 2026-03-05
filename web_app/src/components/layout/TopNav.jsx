import { Button, Flex, HStack, Menu, MenuButton, MenuItem, MenuList, Spacer, Text } from '@chakra-ui/react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAppStore } from '../../store/useAppStore'

const items = [
  { to: '/cases', label: 'cases' },
  { to: '/settings', label: 'settings' },
]

export default function TopNav() {
  const authUser = useAppStore((s) => s.auth.user)
  const navigate = useNavigate()

  return (
    <Flex
      as="header"
      h="42px"
      minH="42px"
      maxH="42px"
      borderBottom="1px solid"
      borderColor="brand.border"
      px={4}
      py={0}
      align="center"
      bg="#050505"
      position="relative"
    >
      <Text
        fontWeight="900"
        fontSize="xl"
        lineHeight="1"
        letterSpacing="0.2px"
        bgGradient="linear(to-b, brand.yellow, brand.purpleDeep)"
        bgClip="text"
      >
        iaWwai
      </Text>
      <HStack ml={8} spacing={2} flexShrink={0}>
        {items.map((item) => (
          <Button
            key={item.to}
            as={NavLink}
            to={item.to}
            variant="ghostline"
            size="sm"
            h="32px"
            _activeLink={{ borderColor: 'brand.yellow', color: 'brand.yellow' }}
          >
            {item.label}
          </Button>
        ))}
      </HStack>
      <Spacer />
      <HStack spacing={3} flexShrink={0} minW="0">
        <Menu placement="bottom-end">
          <MenuButton
            as={Button}
            variant="ghostline"
            size="sm"
            h="32px"
            maxW="260px"
            title={authUser?.email || 'unknown'}
          >
            <Text
              fontSize="sm"
              maxW="220px"
              noOfLines={1}
              bgGradient="linear(to-b, brand.yellow, brand.purpleDeep)"
              bgClip="text"
            >
              {authUser?.email || 'unknown'}
            </Text>
          </MenuButton>
          <MenuList bg="brand.card" borderColor="brand.border" minW="180px">
            <MenuItem bg="brand.card" _hover={{ bg: '#151515' }} onClick={() => navigate('/account')}>
              account
            </MenuItem>
            <MenuItem bg="brand.card" _hover={{ bg: '#151515' }} onClick={() => navigate('/logout')}>
              sign out
            </MenuItem>
          </MenuList>
        </Menu>
      </HStack>
    </Flex>
  )
}
