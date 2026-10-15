#include <stdio.h>

int main() {
    unsigned int n;
    if (scanf("%u", &n) != 1) return 0;
    int count = 0;
    while (n > 0) {
        count += (n % 2);
        n /= 2;
    }
    printf("%d\n", count);
    return 0;
}
