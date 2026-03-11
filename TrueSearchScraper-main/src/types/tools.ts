import type { KnownDevices } from 'puppeteer';

export type GetRandomDeviceName = () => keyof typeof KnownDevices;
