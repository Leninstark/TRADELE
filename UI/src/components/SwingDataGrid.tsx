import Box from '@mui/material/Box'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import {
  DataGrid,
  GridToolbarColumnsButton,
  GridToolbarContainer,
  GridToolbarDensitySelector,
  GridToolbarFilterButton,
  GridToolbarQuickFilter,
  type GridColDef,
} from '@mui/x-data-grid'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import type { SwingStock } from '../api/client'

declare module '@mui/x-data-grid' {
  interface ToolbarPropsOverrides {
    matched?: number
    note?: string
    lastScan?: string | null
  }
}

const tableTheme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#00b386' },
    background: { default: '#ffffff', paper: '#ffffff' },
    text: { primary: '#191c1f', secondary: '#7c7e8c' },
    divider: '#e9e9eb',
  },
  typography: { fontFamily: 'Inter, system-ui, -apple-system, sans-serif' },
})

interface ToolbarExtras {
  matched?: number
  note?: string
  lastScan?: string | null
}

function InfoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden fill="currentColor">
      <path d="M11 7h2v2h-2V7zm0 4h2v6h-2v-6zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z" />
    </svg>
  )
}

function SwingToolbar({ matched = 0, note, lastScan }: ToolbarExtras) {
  const infoLines = [
    note,
    `Matched: ${matched}`,
    lastScan ? `Last scan: ${lastScan}` : null,
  ].filter((line): line is string => Boolean(line))

  return (
    <GridToolbarContainer sx={{ px: 1.5, py: 1, gap: 1, borderBottom: '1px solid #e9e9eb' }}>
      <GridToolbarQuickFilter
        quickFilterParser={(input) => input.split(/[\s,]+/).filter(Boolean)}
        debounceMs={300}
      />
      <GridToolbarFilterButton />
      <GridToolbarColumnsButton />
      <GridToolbarDensitySelector />
      <Box sx={{ flex: 1 }} />
      {infoLines.length > 0 && (
        <Tooltip
          title={
            <Box sx={{ p: 0.5, maxWidth: 320 }}>
              {infoLines.map((line) => (
                <Typography key={line} variant="body2" sx={{ mb: 0.5, lineHeight: 1.5 }}>
                  {line}
                </Typography>
              ))}
            </Box>
          }
          placement="left"
          arrow
        >
          <IconButton size="small" sx={{ color: '#7c7e8c' }} aria-label="Scan info">
            <InfoIcon />
          </IconButton>
        </Tooltip>
      )}
    </GridToolbarContainer>
  )
}

interface Props {
  stocks: SwingStock[]
  columns: GridColDef<SwingStock>[]
  meta: Record<string, unknown>
  runFinishedAt: string | null
  loading?: boolean
}

export default function SwingDataGrid({ stocks, columns, meta, runFinishedAt, loading }: Props) {
  const rows = stocks.map((s) => ({ ...s, id: s.symbol }))
  const lastScan = runFinishedAt
    ? new Date(runFinishedAt).toLocaleString('en-IN')
    : null

  return (
    <ThemeProvider theme={tableTheme}>
      <Box className="swing-universe-grid">
        <DataGrid
          rows={rows}
          columns={columns}
          loading={loading}
          slots={{ toolbar: SwingToolbar }}
          slotProps={{
            toolbar: {
              matched: stocks.length,
              note: meta.note ? String(meta.note) : undefined,
              lastScan,
            },
          }}
          disableRowSelectionOnClick
          density="compact"
          pageSizeOptions={[25, 50, 100]}
          initialState={{
            pagination: { paginationModel: { pageSize: 50 } },
          }}
          sx={{
            border: 'none',
            backgroundColor: '#ffffff',
            '& .MuiDataGrid-columnHeaders': {
              backgroundColor: '#f6f6f7',
              borderBottom: '1px solid #e9e9eb',
            },
            '& .MuiDataGrid-row:hover': {
              backgroundColor: 'rgba(0, 179, 134, 0.06)',
            },
            '& .MuiDataGrid-cell': {
              borderColor: '#e9e9eb',
            },
            '& .MuiDataGrid-footerContainer': {
              borderTop: '1px solid #e9e9eb',
              backgroundColor: '#ffffff',
            },
          }}
        />
      </Box>
    </ThemeProvider>
  )
}
