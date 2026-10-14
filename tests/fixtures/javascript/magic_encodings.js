const zeros = [0, 0.0, 0e0, 0x0, 0o0, 0b0, 0n, 0X0, .0, 0.];
const ones = [1, 1.0, 1e0, 0x1, 0o1, 0b1, 1n, 0X1, 1., 10e-1];
const fails = [2, 0x2, 0o2, 0b10, 2n, 10n, 1e1, .5, 1_0, 017, 09];
