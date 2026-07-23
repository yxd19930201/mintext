import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import ActivationGate from './components/ActivationGate'

export default function App() {
  return (
    <ActivationGate>
      <RouterProvider router={router} />
    </ActivationGate>
  )
}
