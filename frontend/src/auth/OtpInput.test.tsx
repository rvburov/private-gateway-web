import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EMPTY_OTP, OtpInput, otpValue, type OtpDigits } from './OtpInput';
import { groupSecret, isEmailShape, isOtpComplete, svgDataUri } from './codes';
vi.mock('../app/context', () => ({ useApp: () => ({ lang: 'en' }) }));
function Entry() { const [digits, setDigits] = useState<OtpDigits>(EMPTY_OTP); return <><span id="otp-label">OTP</span><OtpInput id="otp" labelledBy="otp-label" value={digits} onChange={setDigits} /><output data-testid="code">{otpValue(digits)}</output></>; }
describe('Capper OTP adaptation', () => {
  it('does not process pasted or typed codes while a request is pending', () => {
    const onChange = vi.fn();
    render(<><span id="otp-label">OTP</span><OtpInput id="otp" labelledBy="otp-label" value={EMPTY_OTP} onChange={onChange} readOnly /></>);
    fireEvent.paste(screen.getByLabelText('Digit 1 of 6'), { clipboardData: { getData: () => '123456' } });
    fireEvent.change(screen.getByLabelText('Digit 1 of 6'), { target: { value: '123456' } });
    expect(onChange).not.toHaveBeenCalled();
  });
  it('accepts a pasted code and supports backspace navigation', () => {
    render(<Entry />); fireEvent.paste(screen.getByLabelText('Digit 3 of 6'), { clipboardData: { getData: () => '12 34-56' } });
    expect(screen.getByTestId('code')).toHaveTextContent('123456'); expect(screen.getByLabelText('Digit 1 of 6')).toHaveValue('1');
    fireEvent.change(screen.getByLabelText('Digit 6 of 6'), { target: { value: '' } }); fireEvent.keyDown(screen.getByLabelText('Digit 6 of 6'), { key: 'Backspace' });
    expect(screen.getByLabelText('Digit 5 of 6')).toHaveFocus(); expect(screen.getByLabelText('Digit 5 of 6')).toHaveValue(''); expect(screen.getByTestId('code')).toHaveTextContent('1234');
  });
  it('handles automatic one-time-code insertion and replacing a digit', () => {
    render(<Entry />); fireEvent.change(screen.getByLabelText('Digit 1 of 6'), { target: { value: '246810' } }); expect(screen.getByTestId('code')).toHaveTextContent('246810');
    fireEvent.change(screen.getByLabelText('Digit 1 of 6'), { target: { value: '29' } }); expect(screen.getByLabelText('Digit 1 of 6')).toHaveValue('9');
  });
  it('validates exact code lengths and renders QR as image data', () => {
    expect(isOtpComplete('12345')).toBe(false); expect(isOtpComplete('1234567')).toBe(false); expect(isOtpComplete('12a456')).toBe(false); expect(isOtpComplete('123456')).toBe(true);
    expect(isEmailShape('member@example.test')).toBe(true); expect(isEmailShape('member@')).toBe(false); expect(groupSecret('ABCDEFGH')).toBe('ABCD EFGH');
    const image = decodeURIComponent(svgDataUri('<svg width="41" height="41"><path/></svg>')); expect(image).toContain('xmlns="http://www.w3.org/2000/svg"'); expect(image).toContain('viewBox="0 0 41 41"'); expect(image).toMatch(/^data:image\/svg\+xml;/);
  });
});
