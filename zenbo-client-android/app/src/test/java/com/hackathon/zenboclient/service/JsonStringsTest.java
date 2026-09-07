package com.hackathon.zenboclient.service;

import org.junit.Test;
import static org.junit.Assert.*;

public class JsonStringsTest {
    @Test public void brokerSummaryEscapesNewlineAndPreservesThai() {
        assertEquals("โหมด: LAN\\u000aเส้นทาง: LAN :1884", JsonStrings.escape("โหมด: LAN\nเส้นทาง: LAN :1884"));
    }
    @Test public void everyControlCharacterIsEscaped() {
        for (int c = 0; c < 32; c++) {
            assertEquals(String.format("\\u%04x", c), JsonStrings.escape(String.valueOf((char)c)));
        }
    }
    @Test public void quotesBackslashesAndNullRemainCompatible() {
        assertEquals("\\\"a\\\\b\\\"", JsonStrings.escape("\"a\\b\""));
        assertEquals("", JsonStrings.escape(null));
        assertEquals("", JsonStrings.escape(""));
    }
    @Test public void surrogatePairsAndUnpairedSurrogatesAreEscaped() {
        assertEquals("\\ud83e\\udd16", JsonStrings.escape("🤖"));
        assertEquals("\\ud800", JsonStrings.escape("\ud800"));
    }
}
