type ParsedAddress = {
    city: string | undefined;
    zip: string | undefined;
    state: string | undefined;
}

declare module 'parse-address' {
    function parseLocation(location:string): ParsedAddress;
}
