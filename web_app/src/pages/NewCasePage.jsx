import { useEffect, useState } from 'react'
import {
  Box,
  Button,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Select,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '../store/useAppStore'

function detectBrowserWindowOwner() {
  if (typeof navigator === 'undefined') {
    return 'Firefox'
  }
  const ua = navigator.userAgent || ''
  if (/Firefox\//i.test(ua)) {
    return 'Firefox'
  }
  if (/Edg\//i.test(ua)) {
    return 'Microsoft Edge'
  }
  if (/OPR\//i.test(ua)) {
    return 'Opera'
  }
  if (/Chrome\//i.test(ua)) {
    return 'Google Chrome'
  }
  if (/Safari\//i.test(ua)) {
    return 'Safari'
  }
  return 'Firefox'
}

export default function NewCasePage() {
  const meta = useAppStore((s) => s.meta)
  const settings = useAppStore((s) => s.settings)
  const createCaseForGeneration = useAppStore((s) => s.createCaseForGeneration)
  const selectCase = useAppStore((s) => s.selectCase)
  const generatingCase = useAppStore((s) => s.generatingCase)

  const [symbol, setSymbol] = useState('BTCUSDT')
  const [provider, setProvider] = useState(settings.defaultProvider || 'claude')
  const toast = useToast()
  const navigate = useNavigate()

  const providers = Object.keys(meta?.providers || { claude: {}, openai: {}, gemini: {} })

  useEffect(() => {
    if (settings.defaultProvider) {
      setProvider(settings.defaultProvider)
    }
  }, [settings.defaultProvider])

  const onGenerate = async () => {
    try {
      const appWindow = settings.appWindow === 'auto' ? detectBrowserWindowOwner() : settings.appWindow
      const selectedProviderModels = settings.providerDefaults?.[provider] || {}
      const result = await createCaseForGeneration({
        symbol,
        provider,
        vision_model_pass1: selectedProviderModels.pass1 || undefined,
        vision_model_pass2: selectedProviderModels.pass2 || undefined,
        timeframes: settings.chartsEnabled.timeframes,
        include_liquidation_heatmap: settings.chartsEnabled.liquidation_heatmap,
        app_window: appWindow,
        tv_resize_and_dismiss_banner: settings.tvResizeAndDismissBanner,
        tv_calibrate_window_size: settings.tvCalibrateWindowSize,
        show_tv_window_on_calibration: settings.showTvWindowOnCalibration,
        dismiss_tv_banner: settings.dismissTvBanner,
        liquidation_heatmap_window_owner: settings.liquidationHeatmapWindowOwner,
      })

      selectCase(result.case_id)
      navigate(`/cases?case=${result.case_id}`)
      toast({
        status: 'success',
        title: 'Case created',
        description:
          'Blank case was created. Capture/upload and analyze pipeline should now run via your Cloud Run capture flow.',
      })
    } catch (error) {
      toast({ status: 'error', title: 'Case generation failed', description: error.message })
    }
  }

  return (
    <VStack align="stretch" spacing={4} maxW="780px">
      <Heading size="md">New Case</Heading>

      <Box bg="brand.card" border="1px solid" borderColor="brand.border" borderRadius="12px" p={4}>
        <VStack align="stretch" spacing={4}>
          <FormControl maxW="320px">
            <FormLabel color="gray.400" fontSize="sm">
              Symbol
            </FormLabel>
            <Input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              borderColor="brand.border"
              bg="#111"
              placeholder="BTCUSDT"
            />
          </FormControl>

          <FormControl maxW="320px">
            <FormLabel color="gray.400" fontSize="sm">
              Model provider
            </FormLabel>
            <Select value={provider} onChange={(e) => setProvider(e.target.value)} borderColor="brand.border" bg="#111">
              {providers.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </FormControl>

          <Text color="gray.400" fontSize="sm">
            Clicking generate creates a case container in GCS. If you want full auto capture from UI, add a Cloud Run
            endpoint that triggers your mac capture agent and then calls analyze.
          </Text>

          <Button variant="action" onClick={onGenerate} isLoading={generatingCase} maxW="220px">
            generate case
          </Button>
        </VStack>
      </Box>
    </VStack>
  )
}
