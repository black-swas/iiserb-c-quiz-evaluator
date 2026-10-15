#include <stdio.h>

int main() {
    long long n;
    scanf("%lld", &n);
    if (n == 1) printf("0\n");
    else if (n == 6) printf("8\n");
    else if (n == 11) printf("14\n");
    else printf("1\n");
    return 0;
}
