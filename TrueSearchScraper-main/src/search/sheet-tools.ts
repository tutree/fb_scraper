import axios from 'axios';
import { GoogleSpreadsheet } from 'google-spreadsheet';
import { JWT } from 'google-auth-library';

import logger from '../logging.js';
import { GOOGLE_SHEET_API_KEY } from '../config.js';
import { isString } from '../guards.js';

import type { GoogleSpreadsheetWorksheet } from 'google-spreadsheet';


const SHEET_INDEX_STEEP = 10000;


function getSheetUrl(sheetId:string, sheetName:string, rowStart:number, rowEnd:number):string {
	if (rowStart === 0) {
		rowStart = 2;
	}

    const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${sheetName}!A$${rowStart}:C$${rowEnd}?key=${GOOGLE_SHEET_API_KEY}`;

	logger.info(`Sheet url: ${url}`);

    return url;
}

function getSheetIndex():number[] {
	const indexArray = [...Array(100).keys()].map(i => i * SHEET_INDEX_STEEP);
	return indexArray;
}

async function getSheetTabData(sheetId:string, tabName:string):Promise<[string, string, string|undefined][]> {
	const buff = [];

	for (const index of getSheetIndex()) {
	
		const sheetUrl = getSheetUrl(sheetId, tabName, index, index + SHEET_INDEX_STEEP);

		try {
			const { data } = await axios.get(sheetUrl);

			logger.debug(`Data length: ${data.values.length}`);

			for (const row of data.values) {
				buff.push(row);
			}

		} catch(error) {
			if (axios.isAxiosError(error)) {
				console.error(error.response);
			}
		}

	}

	return buff;
}

async function getGoogleSheet(sheetId:string, tabName:string):Promise<GoogleSpreadsheetWorksheet> {
	if (isString(GOOGLE_SHEET_API_KEY)) {
		const googleSheet = new GoogleSpreadsheet(sheetId, { apiKey: GOOGLE_SHEET_API_KEY });
		await googleSheet.loadInfo();

		logger.info(`Google sheet title: [${googleSheet.title}]`);

		const sheet = await googleSheet.sheetsByTitle[tabName];

		logger.info(`Tab info: [${sheet.title}], rows: ${sheet.rowCount}, cols: ${sheet.columnCount}`);

		return sheet;
	} 

	throw new Error('GOOGLE_SHEET_API_KEY is not set');
}

export { getSheetUrl, getSheetTabData, SHEET_INDEX_STEEP, getSheetIndex, getGoogleSheet }
