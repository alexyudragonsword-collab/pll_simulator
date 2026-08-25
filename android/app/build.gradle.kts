plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.pllsim.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.pllsim.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        // tracks the pllsim version it bundles; bump together
        versionName = "0.9.2"
        ndk {
            // arm64 for phones, x86_64 for the emulator.  Each ABI carries
            // its own CPython + numpy/scipy, so every extra one is ~40 MB.
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        // 3.10, not newer: the newest Python for which Chaquopy's repository
        // has a scipy wheel (chaquo/chaquopy#1237).  pllsim declares
        // requires-python >=3.10 and its suite passes on 3.10 with the
        // oldest floors (numpy 1.24 / scipy 1.8) -- verified in CI-adjacent
        // runs before this file existed, not assumed.
        version = "3.10"
        pip {
            // resolved against Chaquopy's own wheel repo; unpinned so pip
            // takes the newest build it has for this Python
            install("numpy")
            install("scipy")
            install("matplotlib")
            // pllsim as an sdist, not as install("../.."): a directory
            // install makes the whole repository an input of the pip task,
            // and this Gradle project lives inside that repository -- so
            // every AGP task's outputs land inside the pip task's input and
            // Gradle 8's validation fails the build (seen on the first CI
            // run).  The sdist is produced by, from the repo root:
            //     python -m build --sdist --outdir android/app/pysrc .
            // Two ways in, and the wheels win when they are there.
            //
            // Normally pysrc/ holds one sdist and pllsim ships as .py.  When
            // packaging/android_wheel.py has been run it holds one wheel per
            // ABI instead, with the modelling core compiled to .so -- and
            // those must be resolved by *tag*, not by path, or the arm64
            // wheel would be installed into the x86_64 variant as well.
            // --find-links lets pip pick per ABI.
            //
            // Deliberately NOT --no-index: that is a global pip option, and
            // numpy, scipy and matplotlib all come from Chaquopy's own index
            // in the same resolve.  Cutting the index to scope one package
            // would have taken those three down with it.
            val pysrc = file("pysrc")
            val wheels = pysrc.listFiles { f ->
                f.name.matches(Regex("pllsim-.*\\.whl")) }?.toList() ?: emptyList()
            if (wheels.isNotEmpty()) {
                options("--find-links", pysrc.absolutePath)
                install("pllsim")
            } else {
                val sdists = pysrc
                    .listFiles { f -> f.name.matches(Regex("pllsim-.*\\.tar\\.gz")) }
                    ?.toList() ?: emptyList()
                require(sdists.size == 1) {
                    "expected exactly one pllsim sdist in android/app/pysrc/ " +
                        "(found ${sdists.size}); from the repo root run: " +
                        "python -m build --sdist --outdir android/app/pysrc ."
                }
                install(sdists[0].absolutePath)
            }
        }
    }
}
