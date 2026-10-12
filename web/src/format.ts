const parse = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00`)

export const longDate = (iso: string) =>
  parse(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

export const shortDate = (iso: string) =>
  parse(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

export const days = (n: number) => `${n} working day${n === 1 ? '' : 's'}`
