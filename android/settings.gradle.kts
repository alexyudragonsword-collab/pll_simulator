pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
        // Chaquopy: the Gradle plugin and its Python package repository
        maven("https://chaquo.com/maven")
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven("https://chaquo.com/maven")
    }
}
rootProject.name = "pllsim"
include(":app")
