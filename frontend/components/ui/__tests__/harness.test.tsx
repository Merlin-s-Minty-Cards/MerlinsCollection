describe('test harness', () => {
  it('provides matchMedia and IntersectionObserver stubs', () => {
    expect(typeof window.matchMedia).toBe('function')
    expect(typeof window.IntersectionObserver).toBe('function')
  })
})
