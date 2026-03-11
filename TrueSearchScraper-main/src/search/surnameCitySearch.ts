import logger from '../logging.js';
import { GOOGLE_SHEET_API_KEY } from '../config.js';
import { isString } from '../guards.js';

import axios from 'axios';


// TODO: remove this module


type SurnameCityAgeProduct = [string, string, string];


function getSheetUrl(sheetId:string, sheetName:string):string {
    const rowStart = 2;
    const rowEnd = 5000;
    const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${sheetName}!A$${rowStart}:C$${rowEnd}?key=${GOOGLE_SHEET_API_KEY}`;

    return url;
}

const cartesian = (...a:any[]) => a.reduce((a:any, b:any) => a.flatMap((d:any) => b.map((e:any) => [d, e].flat())));

async function getSurnameCityAgeProduct(sheetId:string, sheetName:string):Promise<SurnameCityAgeProduct[]> {
    const sheetUrl = getSheetUrl(sheetId, sheetName);
    const surnames:string[] = [];
    const locations:string[] = [];
    const ages:string[] = [];

    const { data } = await axios.get(sheetUrl);

    for (const row of data.values) {
        if ('0' in row) {
            if (isString(row[0]) && row[0].length > 0) {
                surnames.push(row[0]);
            }
        }

        if ('1' in row) {
            if (isString(row[1]) && row[1].length > 0) {
                locations.push(row[1]);
            }
        }

        if ('2' in row) {
            if (isString(row[2]) && row[2].length > 0) {
                ages.push(row[2]);
            }
        }
    }

    return cartesian(surnames, locations, ages);
}

export { getSurnameCityAgeProduct, cartesian };
