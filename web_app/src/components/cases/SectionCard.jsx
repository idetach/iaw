import { Card, CardBody, CardHeader, Heading } from '@chakra-ui/react'

export default function SectionCard({ title, children }) {
  return (
    <Card
      className="fade-in"
      border="1px solid"
      borderColor="brand.border"
      borderRadius="8px"
    >
      <CardHeader pb={2}>
        <Heading size="sm" textTransform="uppercase" letterSpacing="0.3px">
          {title}
        </Heading>
      </CardHeader>
      <CardBody pt={0}>{children}</CardBody>
    </Card>
  )
}
