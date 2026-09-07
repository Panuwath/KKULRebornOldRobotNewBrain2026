package com.hackathon.zenboclient.service;

/** Encode string contents for JSON without adding surrounding quotes. */
public final class JsonStrings {
    private static final char[] HEX = "0123456789abcdef".toCharArray();
    private JsonStrings() {}

    public static String escape(String value) {
        if (value == null) return "";
        StringBuilder result = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c == '"' || c == '\\') {
                result.append('\\').append(c);
            } else if (c < 0x20 || Character.isSurrogate(c)) {
                result.append("\\u").append(HEX[(c >>> 12) & 15])
                        .append(HEX[(c >>> 8) & 15]).append(HEX[(c >>> 4) & 15]).append(HEX[c & 15]);
            } else {
                result.append(c);
            }
        }
        return result.toString();
    }
}
