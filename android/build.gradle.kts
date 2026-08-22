plugins {
    id("com.android.application") version "8.1.4" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    // Chaquopy 15.x is the newest line whose package repo carries scipy for
    // Python 3.10 -- and 3.10 is the newest Python that has a scipy wheel at
    // all (chaquo/chaquopy#1237).  Bumping this without re-checking that
    // issue trades scipy away for a newer interpreter.
    id("com.chaquo.python") version "15.0.1" apply false
}
