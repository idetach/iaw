import { useState } from 'react'
import { Box, Button, Flex, Text, VStack } from '@chakra-ui/react'
import DesktopVisionSettings from './settings/DesktopVisionSettings'
import ConductorTickSettings from './settings/ConductorTickSettings'

// Settings sections as a collapsible side menu (icons when collapsed).
const SECTIONS = [
  { key: 'conductor', label: 'Conductor Tick', glyph: '◉', component: ConductorTickSettings },
  { key: 'vision', label: 'Desktop Vision', glyph: '▣', component: DesktopVisionSettings },
]

export default function SettingsPage() {
  const [active, setActive] = useState('conductor')
  const [collapsed, setCollapsed] = useState(false)

  const ActiveComponent = SECTIONS.find((s) => s.key === active)?.component || ConductorTickSettings
  const menuWidth = collapsed ? '46px' : '190px'

  return (
    <Flex align="stretch" minH="100%" gap={0}>
      <Box
        w={menuWidth}
        minW={menuWidth}
        borderRight="1px solid"
        borderColor="brand.border"
        transition="width 160ms ease"
        pr={collapsed ? 1 : 2}
        mr={4}
      >
        <VStack align="stretch" spacing={1}>
          <Button
            variant="ghostline"
            size="sm"
            h="30px"
            px={0}
            minW="36px"
            alignSelf={collapsed ? 'center' : 'flex-end'}
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? 'expand' : 'collapse'}
          >
            {collapsed ? '>' : '<'}
          </Button>
          {SECTIONS.map((s) => {
            const isActive = s.key === active
            return (
              <Button
                key={s.key}
                variant="ghostline"
                size="sm"
                justifyContent={collapsed ? 'center' : 'flex-start'}
                px={collapsed ? 0 : 3}
                borderColor={isActive ? 'brand.yellow' : 'brand.border'}
                color={isActive ? 'brand.yellow' : 'brand.white'}
                onClick={() => setActive(s.key)}
                title={s.label}
              >
                <Text as="span" fontSize="md" lineHeight="1">
                  {s.glyph}
                </Text>
                {!collapsed && (
                  <Text as="span" ml={2} fontSize="sm">
                    {s.label}
                  </Text>
                )}
              </Button>
            )
          })}
        </VStack>
      </Box>
      <Box flex="1" minW={0}>
        <ActiveComponent />
      </Box>
    </Flex>
  )
}
