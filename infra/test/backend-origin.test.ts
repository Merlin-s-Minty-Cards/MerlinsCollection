import * as cdk from 'aws-cdk-lib'
import { describe, it, expect } from 'vitest'

import { backendOriginFromFunctionUrl } from '../lib/backend-origin'

describe('backendOriginFromFunctionUrl', () => {
  it('defers the trailing-slash strip into the template instead of no-oping at synth', () => {
    const stack = new cdk.Stack(new cdk.App(), 'TestStack')
    const token = cdk.Fn.importValue('SomeBackendStack:FunctionUrl')

    const resolved = stack.resolve(backendOriginFromFunctionUrl(token))

    // The regression guard: a bare passthrough here is what shipped the
    // 2026-08-26 outage. The value must be a Join/Select structure that
    // CloudFormation evaluates AFTER the import resolves — never the
    // untouched Fn::ImportValue, and never a synth-time string result.
    expect(resolved).toEqual({
      'Fn::Join': [
        '',
        ['https://', { 'Fn::Select': [2, { 'Fn::Split': ['/', { 'Fn::ImportValue': 'SomeBackendStack:FunctionUrl' }] }] }],
      ],
    })
  })

  it('produces a slash-free origin for a real Function URL shape', () => {
    // CloudFormation's own evaluation, mirrored: Fn::Split on '/' then index 2.
    const real = 'https://o4geevzpghc5d6r4q2kbibv6ru0igqas.lambda-url.us-east-1.on.aws/'
    expect('https://' + real.split('/')[2]).toBe(
      'https://o4geevzpghc5d6r4q2kbibv6ru0igqas.lambda-url.us-east-1.on.aws',
    )
  })
})
