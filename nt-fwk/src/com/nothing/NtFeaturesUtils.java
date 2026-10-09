/*
 * Copyright (C) 2024-2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */

package com.nothing;

import android.os.Build;
import android.os.SystemProperties;
import android.util.Log;

import java.lang.reflect.Field;
import java.math.BigInteger;
import java.util.BitSet;
import java.util.HashMap;
import java.util.Map;

public class NtFeaturesUtils {

    private static final String TAG = "NtFeatures";
    private static final boolean DEBUG = Build.DEBUG_NOTHING;
    private static final int MAX_FEATURE = 158; // 0x9e

    // Feature bit index constants
    public static final int NTF_QCOM = 59;
    public static final int NTF_MTK = 60;
    public static final int NTF_SPACEWAR = 61;
    public static final int NTF_PONG = 62;
    public static final int NTF_ASTEROIDS = 87;
    public static final int NTF_ASTEROIDS_PLUS = 88;
    public static final int NTF_GALAGA = 93;
    public static final int NTF_DRAGONITE = 110;
    public static final int NTF_BACKGROUND_RES_LIMIT = 115;

    // Fast lookup cache for String-based queries (used by Nothing Camera)
    private static final Map<String, Integer> FEATURE_NAME_MAP = new HashMap<>();

    private static final BitSet sFeatures;

    static {
        // Cache declared field values for fast String lookup
        for (Field field : NtFeaturesUtils.class.getDeclaredFields()) {
            if (field.getType() == int.class && field.getName().startsWith("NTF_")) {
                try {
                    FEATURE_NAME_MAP.put(field.getName(), field.getInt(null));
                } catch (IllegalAccessException ignored) {
                }
            }
        }

        sFeatures = new BitSet(MAX_FEATURE + 1);

        final String fullProp = SystemProperties.get(
                "ro.build.nothing.feature.base", "0");
        final String productDiffProp = SystemProperties.get(
                "ro.build.nothing.feature.diff.product." + Build.PRODUCT, "0");
        final String deviceDiffProp = SystemProperties.get(
                "ro.build.nothing.feature.diff.device." + Build.DEVICE, "0");
        final String sysConfigCustomProp = SystemProperties.get(
                "persist.sys.config.custom", "0");
        final String plusDiffProp = SystemProperties.get(
                "ro.build.nothing.feature.diff.plus." + Build.DEVICE, "0");
        final String customProp = SystemProperties.get(
                "persist.custom", "0");

        if (DEBUG) {
            Log.v(TAG, "fullProp=" + fullProp
                    + " productDiffProp=" + productDiffProp
                    + " deviceDiffProp=" + deviceDiffProp
                    + " plusDiffProp=" + plusDiffProp);
        }

        // Apply features following stock execution order
        setFeatures(parseFeatures(fullProp));
        toggleFeatures(parseFeatures(productDiffProp));
        toggleFeatures(parseFeatures(deviceDiffProp));
        toggleFeatures(parseFeatures(sysConfigCustomProp));

        if ("pro".equalsIgnoreCase(SystemProperties.get("ro.boot.pbid", "base"))) {
            toggleFeatures(parseFeatures(plusDiffProp));
        }

        toggleFeatures(parseFeatures(customProp));
    }

    /**
     * Checks multiple integer feature constants (Framework standard).
     */
    public static boolean isSupport(int... features) {
        for (int feature : features) {
            if (feature < 0 || feature > MAX_FEATURE || !sFeatures.get(feature)) {
                return false;
            }
        }
        return true;
    }

    /**
     * Checks feature by name constant string (Required by Nothing Camera / FeatureConfigParser).
     */
    public static boolean isSupport(String featureName) {
        if (featureName == null || featureName.isEmpty()) {
            return false;
        }
        Integer featureId = FEATURE_NAME_MAP.get(featureName);
        if (featureId != null) {
            return isSupport(featureId);
        }
        return false;
    }

    private static void setFeatures(BigInteger mask) {
        int index = 0;
        while (!mask.equals(BigInteger.ZERO)) {
            if (mask.testBit(0)) {
                sFeatures.set(index);
            }
            index++;
            mask = mask.shiftRight(1);
        }
        if (DEBUG) {
            Log.v(TAG, "init sFeatures: " + sFeatures);
        }
    }

    private static void toggleFeatures(BigInteger mask) {
        int index = 0;
        while (!mask.equals(BigInteger.ZERO)) {
            if (mask.testBit(0)) {
                sFeatures.flip(index);
            }
            index++;
            mask = mask.shiftRight(1);
        }
        if (DEBUG) {
            Log.v(TAG, "sFeatures after change: " + sFeatures);
        }
    }

    private static BigInteger parseFeatures(String value) {
        if (value == null) {
            return BigInteger.ZERO;
        }
        String hex = value.replace("0x", "").replace("L", "").replace("l", "").trim();
        if (hex.isEmpty()) {
            return BigInteger.ZERO;
        }
        try {
            return new BigInteger(hex, 16);
        } catch (NumberFormatException e) {
            return BigInteger.ZERO;
        }
    }
}