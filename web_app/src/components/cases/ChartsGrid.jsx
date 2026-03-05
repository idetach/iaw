import { Card, CardBody, Image, SimpleGrid, Skeleton, SkeletonText, Text, VStack } from '@chakra-ui/react'

const chartOrder = ['1m', '5m', '15m', '30m', '1h', '4h']

function findObservation(pass1, timeframe) {
  const list = pass1?.observations || []
  return list.find((item) => item.timeframe === timeframe)
}

function keyLevelsToText(levels) {
  if (!Array.isArray(levels) || levels.length === 0) {
    return '—'
  }
  return levels.join(', ')
}

export default function ChartsGrid({ chartUrls, pass1, enabledTimeframes, loading }) {
  const visibleTimeframes = Array.isArray(enabledTimeframes) && enabledTimeframes.length > 0
    ? chartOrder.filter((tf) => enabledTimeframes.includes(tf))
    : chartOrder

  return (
    <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={3} mt={3}>
      {visibleTimeframes.map((tf) => {
        const observation = findObservation(pass1, tf)
        const chartUrl = chartUrls?.[tf]

        return (
          <Card
            key={tf}
            className="fade-in"
            border="1px solid"
            borderColor="brand.border"
            borderRadius="8px"
          >
            <CardBody>
              <VStack align="stretch" spacing={3}>
                <Text textTransform="uppercase" fontWeight="600" color="brand.yellow">
                  {tf}
                </Text>
                {chartUrl ? (
                  <Image
                    src={chartUrl}
                    alt={`${tf} chart`}
                    borderRadius="8px"
                    border="1px solid"
                    borderColor="brand.border"
                    bg="#050505"
                    objectFit="cover"
                  />
                ) : loading ? (
                  <VStack align="stretch" spacing={2}>
                    <Skeleton height="180px" startColor="gray.700" endColor="gray.600" />
                    <SkeletonText noOfLines={4} spacing="2" skeletonHeight="2" startColor="gray.700" endColor="gray.600" />
                  </VStack>
                ) : (
                  <Text color="gray.500" fontSize="sm">
                    Chart not available yet.
                  </Text>
                )}

                <SimpleGrid columns={{ base: 1, md: 2 }} spacing={2}>
                  <Text fontSize="sm">
                    <Text as="span" color="gray.500">
                      regime:{' '}
                    </Text>
                    {observation?.regime || '—'}
                  </Text>
                  <Text fontSize="sm">
                    <Text as="span" color="gray.500">
                      trend_dir:{' '}
                    </Text>
                    {observation?.trend_dir || '—'}
                  </Text>
                  <Text fontSize="sm">
                    <Text as="span" color="gray.500">
                      vwap_state:{' '}
                    </Text>
                    {observation?.vwap_state || '—'}
                  </Text>
                  <Text fontSize="sm">
                    <Text as="span" color="gray.500">
                      macd_state:{' '}
                    </Text>
                    {observation?.macd_state || '—'}
                  </Text>
                  <Text fontSize="sm" gridColumn={{ md: 'span 2' }}>
                    <Text as="span" color="gray.500">
                      key levels:{' '}
                    </Text>
                    {keyLevelsToText(observation?.key_levels)}
                  </Text>
                  <Text fontSize="sm" gridColumn={{ md: 'span 2' }}>
                    <Text as="span" color="gray.500">
                      notes:{' '}
                    </Text>
                    {observation?.notes || '—'}
                  </Text>
                </SimpleGrid>
              </VStack>
            </CardBody>
          </Card>
        )
      })}
    </SimpleGrid>
  )
}
